# cogs/casino_dice.py - Updated with consistent embed layout
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

class DiceGameCog(commands.Cog):
    """Simple dice guessing game - Multi-server aware with standardized embeds"""

    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("주사위")
        self.logger.info("주사위 게임 시스템이 초기화되었습니다.")

    def get_dice_visual(self, value):
        """Get visual representation of dice value with colors"""
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
        """Create standardized visual dice display"""
        dice_display = f"{self.get_dice_visual(die1)} {self.get_dice_visual(die2)}"

        if rolling:
            return f"{dice_display}\n\n🔄 **굴리는 중...**"
        else:
            return f"{dice_display}\n\n🎯 **합계: {total}**"

    async def validate_game(self, interaction: discord.Interaction, bet: int):
        """Validate game using casino base with booster limits"""
        casino_base = self.bot.get_cog('CasinoBaseCog')
        if not casino_base:
            return False, "카지노 시스템을 찾을 수 없습니다!"

        # Get server-specific limits
        min_bet = get_server_setting(interaction.guild.id, 'dice_min_bet', 5)
        server_max_bet = get_server_setting(interaction.guild.id, 'dice_max_bet', 200)

        # Apply booster limit
        booster_cog = self.bot.get_cog('BoosterPerks')
        if booster_cog:
            max_bet = booster_cog.get_betting_limit(interaction.user)
            # Use the lower of server setting or booster limit
            max_bet = min(server_max_bet, max_bet)
        else:
            max_bet = server_max_bet

        return await casino_base.validate_game_start(
            interaction, "dice_game", bet, min_bet, max_bet
        )

    @app_commands.command(name="주사위", description="주사위 합 맞히기 게임")
    @app_commands.describe(
        bet="베팅 금액",
        guess="예상 합계 (2-12)"
    )
    async def dice_game(self, interaction: discord.Interaction, bet: int, guess: int):
        # Check if casino games are enabled for this server
        if not interaction.guild or not is_feature_enabled(interaction.guild.id, 'casino_games'):
            await interaction.response.send_message("❌ 이 서버에서는 카지노 게임이 비활성화되어 있습니다!", ephemeral=True)
            return

        # Check for overdue loan restrictions
        restriction = await check_user_casino_eligibility(self.bot, interaction.user.id, interaction.guild.id)
        if not restriction['allowed']:
            await interaction.response.send_message(restriction['message'], ephemeral=True)
            return

        if not (2 <= guess <= 12):
            await interaction.response.send_message("주사위 합은 2-12 사이만 가능합니다!", ephemeral=True)
            return

        can_start, error_msg = await self.validate_game(interaction, bet)
        if not can_start:
            await interaction.response.send_message(error_msg, ephemeral=True)
            return

        coins_cog = self.bot.get_cog('CoinsCog')
        if not await coins_cog.remove_coins(interaction.user.id, interaction.guild.id, bet, "dice_game_bet",
                                            "Dice game bet"):
            await interaction.response.send_message("베팅 처리 실패!", ephemeral=True)
            return

        await interaction.response.defer()

        # Initial embed with betting info
        embed = discord.Embed(
            title="🎲 주사위",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )

        # STANDARDIZED FIELD 2: Betting Info (shown during setup)
        embed.add_field(
            name="💳 베팅 정보",
            value=f"💰 **베팅 금액:** {bet:,} 코인\n🎯 **예상 합계:** {guess}",
            inline=False
        )

        embed.set_footer(text=f"Server: {interaction.guild.name}")
        await interaction.edit_original_response(embed=embed)
        await asyncio.sleep(1)

        # Rolling animation
        for i in range(4):
            temp_die1 = random.randint(1, 6)
            temp_die2 = random.randint(1, 6)

            embed = discord.Embed(
                title="🎲 주사위",
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

        # Final roll
        die1 = random.randint(1, 6)
        die2 = random.randint(1, 6)
        total = die1 + die2
        won = total == guess
        total_losses_to_lottery = 0

        # Payout calculation (higher multiplier for harder guesses) - server configurable
        base_multipliers = {2: 35, 3: 17, 4: 11, 5: 8, 6: 6, 7: 5, 8: 6, 9: 8, 10: 11, 11: 17, 12: 35}
        multiplier_modifier = get_server_setting(interaction.guild.id, 'dice_multiplier_modifier', 1.0)
        payout_multipliers = {k: max(1, int(v * multiplier_modifier)) for k, v in base_multipliers.items()}

        payout = 0
        if won:
            payout = bet * payout_multipliers[guess]
            await coins_cog.add_coins(interaction.user.id, interaction.guild.id, payout, "dice_game_win",
                                      f"Dice win: {total}")
        else:
            # Add 50% of loss to lottery pot
            total_losses_to_lottery = int(bet * 0.5)
            from cogs.lottery import add_casino_fee_to_lottery
            await add_casino_fee_to_lottery(self.bot, interaction.guild.id, total_losses_to_lottery)

        # Standardized title and color logic
        if won:
            title = "🎲 주사위 - 🎉 정확히 맞혔습니다!"
            color = discord.Color.green()
        else:
            title = "🎲 주사위 - 😞 아쉽네요!"
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
            value=f"💰 **베팅 금액:** {bet:,} 코인\n🎯 **예상 합계:** {guess}",
            inline=False
        )

        # STANDARDIZED FIELD 3: Game Results
        if won:
            result_text = f"🎯 **정확히 맞혔습니다!** {payout_multipliers[guess]}배 배당"
            profit = payout - bet
            result_info = f"{result_text}\n\n💰 **수익:** {payout:,} 코인\n📈 **순이익:** +{profit:,} 코인"
        else:
            result_text = f"❌ **예상 실패!** (실제: {total})"
            result_info = f"{result_text}\n\n💸 **손실:** {bet:,} 코인"

            # Add lottery contribution info
            if total_losses_to_lottery > 0:
                result_info += f"\n\n🎰 베팅 손실 중 {total_losses_to_lottery:,} 코인이 복권 팟에 추가되었습니다."

        embed.add_field(name="📊 게임 결과", value=result_info, inline=False)

        # STANDARDIZED FIELD 4: Balance Info
        new_balance = await coins_cog.get_user_coins(interaction.user.id, interaction.guild.id)
        embed.add_field(name="", value=f"🏦 **현재 잔액:** {new_balance:,} 코인", inline=False)

        # Standardized footer
        embed.set_footer(text=f"플레이어: {interaction.user.display_name} | Server: {interaction.guild.name}")

        await interaction.edit_original_response(embed=embed)

        self.logger.info(
            f"{interaction.user}가 주사위에서 {bet} 코인 {'승리' if won else '패배'} (예상: {guess}, 실제: {total})",
            extra={'guild_id': interaction.guild.id}
        )


async def setup(bot):
    await bot.add_cog(DiceGameCog(bot))