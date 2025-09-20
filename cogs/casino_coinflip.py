# cogs/casino_coinflip.py - Updated with consistent embed layout and fixed coin handling
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

class CoinflipCog(commands.Cog):
    """Coinflip casino game - Multi-server aware with standardized embeds"""

    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("동전던지기")
        self.logger.info("동전던지기 게임 시스템이 초기화되었습니다.")

    def create_coin_display(self, result=None, flipping=False, choice=None):
        """Create standardized coin display"""
        if flipping:
            return "🪙 **동전이 공중에서 빙글빙글...**\n\n🔄 **던지는 중...**"
        elif result:
            choice_korean = {"heads": "앞면", "tails": "뒷면"}
            result_korean = choice_korean[result]
            chosen_korean = choice_korean[choice] if choice else "?"

            result_emoji = "👑" if result == "heads" else "⚫"
            choice_emoji = "👑" if choice == "heads" else "⚫"

            display = f"🪙 **결과: {result_emoji} {result_korean}**\n"
            display += f"🎯 **예상: {choice_emoji} {chosen_korean}**\n\n"

            if result == choice:
                display += "✅ **적중!**"
            else:
                display += "❌ **빗나감!**"

            return display
        else:
            return "🪙 **동전 던지기 준비**"

    async def validate_game(self, interaction: discord.Interaction, bet: int):
        """Validate game using casino base"""
        casino_base = self.bot.get_cog('CasinoBaseCog')
        if not casino_base:
            return False, "카지노 시스템을 찾을 수 없습니다!"

        # Get server-specific limits
        min_bet = get_server_setting(interaction.guild.id, 'coinflip_min_bet', 5)
        max_bet = get_server_setting(interaction.guild.id, 'coinflip_max_bet', 200)

        return await casino_base.validate_game_start(
            interaction, "coinflip", bet, min_bet, max_bet
        )

    @app_commands.command(name="동전던지기", description="동전 던지기 게임")
    @app_commands.describe(
        bet="베팅 금액",
        choice="앞면(heads) 또는 뒷면(tails)"
    )
    @app_commands.choices(choice=[
        app_commands.Choice(name="👑 앞면 (Heads)", value="heads"),
        app_commands.Choice(name="⚫ 뒷면 (Tails)", value="tails")
    ])
    async def coinflip(self, interaction: discord.Interaction, bet: int, choice: str):
        # Check if casino games are enabled for this server
        if not interaction.guild or not is_feature_enabled(interaction.guild.id, 'casino_games'):
            await interaction.response.send_message("❌ 이 서버에서는 카지노 게임이 비활성화되어 있습니다!", ephemeral=True)
            return

        # Check for overdue loan restrictions
        restriction = await check_user_casino_eligibility(self.bot, interaction.user.id, interaction.guild.id)
        if not restriction['allowed']:
            await interaction.response.send_message(restriction['message'], ephemeral=True)
            return

        # Validate game start (but don't deduct coins yet)
        can_start, error_msg = await self.validate_game(interaction, bet)
        if not can_start:
            await interaction.response.send_message(error_msg, ephemeral=True)
            return

        coins_cog = self.bot.get_cog('CoinsCog')

        # Log initial balance for debugging
        initial_balance = await coins_cog.get_user_coins(interaction.user.id, interaction.guild.id)
        self.logger.info(
            f"{interaction.user} starting coinflip - bet: {bet}, initial balance: {initial_balance}",
            extra={'guild_id': interaction.guild.id}
        )

        await interaction.response.defer()

        # Initial embed with choice display
        choice_display = "👑 **앞면 (Heads)**" if choice == "heads" else "⚫ **뒷면 (Tails)**"
        payout_multiplier = get_server_setting(interaction.guild.id, 'coinflip_payout', 2.0)

        embed = discord.Embed(
            title="🪙 동전던지기",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )

        # STANDARDIZED FIELD 2: Betting Info (shown during setup)
        embed.add_field(
            name="💳 베팅 정보",
            value=f"💰 **베팅 금액:** {bet:,} 코인\n🎯 **예상:** {choice_display} ({payout_multiplier}배 배당)",
            inline=False
        )

        embed.set_footer(text=f"Server: {interaction.guild.name}")
        await interaction.edit_original_response(embed=embed)
        await asyncio.sleep(1)

        # Flipping animation
        flip_emojis = ["🪙", "⚪", "🟡", "⚫"]
        for i in range(4):
            embed = discord.Embed(
                title="🪙 동전던지기",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )

            # STANDARDIZED FIELD 1: Game Display (during flipping)
            embed.add_field(
                name="🎯 동전 결과",
                value=self.create_coin_display(flipping=True),
                inline=False
            )

            # STANDARDIZED FIELD 2: Betting Info
            embed.add_field(
                name="💳 베팅 정보",
                value=f"💰 **베팅 금액:** {bet:,} 코인\n🪙 **상태:** 던지는 중... `{i + 1}/4`",
                inline=False
            )

            embed.set_footer(text=f"Server: {interaction.guild.name}")
            await interaction.edit_original_response(embed=embed)
            await asyncio.sleep(0.5)

        # Determine result first
        result = random.choice(["heads", "tails"])
        won = result == choice
        total_losses_to_lottery = 0

        if won:
            payout = int(bet * payout_multiplier)
            net_change = payout - bet  # This is the profit (could be 0 if payout = bet)

            if net_change > 0:
                # User gains money
                success = await coins_cog.add_coins(
                    interaction.user.id,
                    interaction.guild.id,
                    net_change,
                    "coinflip_win",
                    f"Coinflip win profit: {result} (bet: {bet}, payout: {payout})"
                )
            elif net_change == 0:
                # Break even - no coin change needed
                success = True
            else:
                # This shouldn't happen (payout < bet), but handle it
                success = await coins_cog.remove_coins(
                    interaction.user.id,
                    interaction.guild.id,
                    abs(net_change),
                    "coinflip_loss",
                    f"Coinflip loss: {result} (bet: {bet}, payout: {payout})"
                )
        else:
            # User loses - deduct the bet
            success = await coins_cog.remove_coins(
                interaction.user.id,
                interaction.guild.id,
                bet,
                "coinflip_loss",
                f"Coinflip loss: {result} vs {choice}"
            )
            payout = 0
            net_change = -bet

            # Add 50% of loss to lottery pot
            total_losses_to_lottery = int(bet * 0.5)
            from cogs.lottery import add_casino_fee_to_lottery
            await add_casino_fee_to_lottery(self.bot, interaction.guild.id, total_losses_to_lottery)

        # Check if coin operation succeeded
        if not success:
            embed = discord.Embed(
                title="❌ 오류",
                description="코인 처리 중 오류가 발생했습니다. 관리자에게 문의하세요.",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_footer(text=f"Server: {interaction.guild.name}")
            await interaction.edit_original_response(embed=embed)

            self.logger.error(
                f"Coin operation failed for {interaction.user} in coinflip - bet: {bet}, result: {result}, won: {won}",
                extra={'guild_id': interaction.guild.id}
            )
            return

        # Get final balance for display and logging
        final_balance = await coins_cog.get_user_coins(interaction.user.id, interaction.guild.id)

        # Standardized title and color logic
        if won:
            title = "🪙 동전던지기 - 🎉 승리!"
            color = discord.Color.green()
        else:
            title = "🪙 동전던지기 - 😞 패배!"
            color = discord.Color.red()

        embed = discord.Embed(title=title, color=color, timestamp=discord.utils.utcnow())

        # STANDARDIZED FIELD 1: Game Display
        embed.add_field(
            name="🎯 동전 결과",
            value=self.create_coin_display(result, choice=choice),
            inline=False
        )

        # STANDARDIZED FIELD 2: Betting Info
        choice_display = "👑 **앞면 (Heads)**" if choice == "heads" else "⚫ **뒷면 (Tails)**"
        embed.add_field(
            name="💳 베팅 정보",
            value=f"💰 **베팅 금액:** {bet:,} 코인\n🎯 **예상:** {choice_display}",
            inline=False
        )

        # STANDARDIZED FIELD 3: Game Results
        if won:
            result_text = f"🎯 **적중!** {payout_multiplier}배 배당"
            if net_change > 0:
                result_info = f"{result_text}\n\n💰 **수익:** {payout:,} 코인\n📈 **순이익:** +{net_change:,} 코인"
            else:
                result_info = f"{result_text}\n\n🤝 **무승부** (손익 없음)"
        else:
            result_text = f"❌ **빗나감!**"
            result_info = f"{result_text}\n\n💸 **손실:** {bet:,} 코인"

            # Add lottery contribution info
            if total_losses_to_lottery > 0:
                result_info += f"\n\n🎰 베팅 손실 중 {total_losses_to_lottery:,} 코인이 복권 팟에 추가되었습니다."

        embed.add_field(name="📊 게임 결과", value=result_info, inline=False)

        # STANDARDIZED FIELD 4: Balance Info
        embed.add_field(name="", value=f"🏦 **현재 잔액:** {final_balance:,} 코인", inline=False)

        # Standardized footer
        embed.set_footer(text=f"플레이어: {interaction.user.display_name} | Server: {interaction.guild.name}")

        await interaction.edit_original_response(embed=embed)

        # Enhanced logging with balance tracking
        self.logger.info(
            f"{interaction.user} coinflip result - bet: {bet}, choice: {choice}, result: {result}, won: {won}, "
            f"balance: {initial_balance} -> {final_balance} (change: {final_balance - initial_balance})",
            extra={'guild_id': interaction.guild.id}
        )


async def setup(bot):
    await bot.add_cog(CoinflipCog(bot))