# cogs/casino_blackjack.py - Updated with consistent embed layout
import discord
from discord.ext import commands
from discord import app_commands
import random
from typing import List, Dict

from utils.logger import get_logger
from utils.config import (
    is_feature_enabled,
    get_server_setting
)


class BlackjackView(discord.ui.View):
    """Enhanced Blackjack with double down, insurance, and split"""

    def __init__(self, bot, user_id: int, bet: int):
        super().__init__(timeout=180)
        self.bot = bot
        self.user_id = user_id
        self.bet = bet
        self.game_over = False
        self.doubled_down = False
        self.insurance_bet = 0
        self.is_split = False
        self.current_hand = 0
        self.split_hands = []

        # Create and shuffle deck
        self.deck = self.create_deck()
        random.shuffle(self.deck)

        # Deal initial hands
        self.player_hand = [self.draw_card(), self.draw_card()]
        self.dealer_hand = [self.draw_card(), self.draw_card()]

        # Check for dealer ace (insurance option)
        self.can_insure = self.dealer_hand[0]['rank'] == 'A'

        # Check for natural blackjack
        self.player_blackjack = self.calculate_hand_value(self.player_hand) == 21
        self.dealer_blackjack = self.calculate_hand_value(self.dealer_hand) == 21

        # If player has blackjack, end game immediately
        if self.player_blackjack:
            self.game_over = True

    def create_deck(self) -> List[Dict]:
        """Create multiple decks for more realistic play"""
        suits = ['♠️', '♥️', '♦️', '♣️']
        ranks = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']

        deck = []
        # Use 4 decks for more realistic casino experience
        for _ in range(4):
            for suit in suits:
                for rank in ranks:
                    value = 11 if rank == 'A' else (10 if rank in ['J', 'Q', 'K'] else int(rank))
                    deck.append({'rank': rank, 'suit': suit, 'value': value})

        return deck

    def draw_card(self) -> Dict:
        """Draw a card from deck"""
        if len(self.deck) < 10:  # Reshuffle if running low
            self.deck = self.create_deck()
            random.shuffle(self.deck)
        return self.deck.pop()

    def calculate_hand_value(self, hand: List[Dict]) -> int:
        """Calculate hand value with proper ace handling"""
        total = sum(card['value'] for card in hand)
        aces = sum(1 for card in hand if card['rank'] == 'A')

        while total > 21 and aces > 0:
            total -= 10
            aces -= 1

        return total

    def hand_to_string(self, hand: List[Dict], hide_first: bool = False) -> str:
        """Convert hand to display string"""
        if hide_first:
            return f"🔒 {hand[0]['rank']}{hand[0]['suit']}"
        return ' '.join(f"{card['rank']}{card['suit']}" for card in hand)

    def can_double_down(self) -> bool:
        """Check if player can double down"""
        current_hand = self.split_hands[self.current_hand] if self.is_split else self.player_hand
        return len(current_hand) == 2 and not self.doubled_down and not self.game_over

    def can_split(self) -> bool:
        """Check if player can split"""
        if self.is_split or len(self.player_hand) != 2 or self.game_over:
            return False

        # Can split if both cards have same rank or both are 10-value cards
        card1, card2 = self.player_hand
        return (card1['rank'] == card2['rank'] or
                (card1['value'] == 10 and card2['value'] == 10))

    async def create_embed(self, final: bool = False) -> discord.Embed:
        """Create standardized game state embed"""
        if self.is_split:
            return await self.create_split_embed(final)

        player_value = self.calculate_hand_value(self.player_hand)
        dealer_value = self.calculate_hand_value(self.dealer_hand)

        # Standardized title and color logic
        if self.player_blackjack and self.dealer_blackjack:
            title = "🃏 블랙잭 - 🤝 Push (무승부)"
            color = discord.Color.blue()
        elif self.player_blackjack and not self.dealer_blackjack:
            title = "🃏 블랙잭 - 🎊 블랙잭!"
            color = discord.Color.gold()
        elif player_value > 21:
            title = "🃏 블랙잭 - 💥 버스트!"
            color = discord.Color.red()
        elif final and dealer_value > 21:
            title = "🃏 블랙잭 - 🎉 승리! (딜러 버스트)"
            color = discord.Color.green()
        elif final:
            if player_value > dealer_value:
                title = "🃏 블랙잭 - 🏆 승리!"
                color = discord.Color.green()
            elif player_value < dealer_value:
                title = "🃏 블랙잭 - 😞 패배"
                color = discord.Color.red()
            else:
                title = "🃏 블랙잭 - 🤝 Push (무승부)"
                color = discord.Color.blue()
        else:
            title = "🃏 블랙잭"
            color = discord.Color.blue()

        embed = discord.Embed(title=title, color=color, timestamp=discord.utils.utcnow())

        # STANDARDIZED FIELD 1: Game Display
        game_display = f"**딜러 핸드:**\n{self.hand_to_string(self.dealer_hand, not final and not self.game_over)}"
        if final or self.game_over:
            game_display += f" `({dealer_value})`"
        else:
            game_display += " `(?)`"

        game_display += f"\n\n**플레이어 핸드:**\n{self.hand_to_string(self.player_hand)} `({player_value})`"

        if self.player_blackjack:
            game_display += " (Blackjack)"
        elif any(c['rank'] == 'A' for c in self.player_hand) and player_value <= 21:
            game_display += " (Soft)"

        embed.add_field(name="🎯 게임 현황", value=game_display, inline=False)

        # STANDARDIZED FIELD 2: Betting Info
        bet_info = f"💰 **기본 베팅:** {self.bet:,} 코인"
        if self.doubled_down:
            bet_info += f"\n⬆️ **더블다운:** {self.bet:,} 코인"
        if self.insurance_bet > 0:
            bet_info += f"\n🛡️ **보험료:** {self.insurance_bet:,} 코인"

        total_risk = self.bet * (2 if self.doubled_down else 1) + self.insurance_bet
        bet_info += f"\n📊 **총 베팅:** {total_risk:,} 코인"

        embed.add_field(name="💳 베팅 정보", value=bet_info, inline=False)

        return embed

    async def create_split_embed(self, final: bool = False) -> discord.Embed:
        """Create standardized embed for split hands"""
        embed = discord.Embed(title="🃏 블랙잭 - ✂️ 스플릿", color=discord.Color.purple(), timestamp=discord.utils.utcnow())

        # STANDARDIZED FIELD 1: Game Display
        dealer_value = self.calculate_hand_value(self.dealer_hand)
        game_display = f"**딜러 핸드:**\n{self.hand_to_string(self.dealer_hand, not final and not self.game_over)}"
        if final or self.game_over:
            game_display += f" `({dealer_value})`"
        else:
            game_display += " `(?)`"

        game_display += "\n\n**플레이어 핸드:**"
        for i, hand in enumerate(self.split_hands):
            hand_value = self.calculate_hand_value(hand)
            hand_display = self.hand_to_string(hand)
            status = ""
            if hand_value > 21:
                status = " (버스트)"
            elif hand_value == 21 and len(hand) == 2:
                status = " (21)"

            current_indicator = " 👈" if i == self.current_hand and not final else ""
            game_display += f"\n핸드 {i + 1}: {hand_display} `({hand_value})`{status}{current_indicator}"

        embed.add_field(name="🎯 게임 현황", value=game_display, inline=False)

        # STANDARDIZED FIELD 2: Betting Info
        total_bet = self.bet * 2  # Split doubles the bet
        embed.add_field(name="💳 베팅 정보", value=f"💰 **총 베팅:** {total_bet:,} 코인", inline=False)

        return embed

    async def end_game(self, interaction: discord.Interaction):
        """Handle game end and payouts with standardized result display"""
        self.game_over = True

        # Disable all buttons
        for item in self.children:
            item.disabled = True

        coins_cog = self.bot.get_cog('CoinsCog')
        if not coins_cog:
            return

        if self.is_split:
            await self.end_split_game(interaction)
            return

        player_value = self.calculate_hand_value(self.player_hand)
        dealer_value = self.calculate_hand_value(self.dealer_hand)
        total_payout = 0

        # Calculate main bet payout
        if self.player_blackjack and not self.dealer_blackjack:
            total_payout = int(self.bet * 2.5)
            result_text = f"🎊 **BLACKJACK!**"
        elif self.player_blackjack and self.dealer_blackjack:
            total_payout = self.bet
            result_text = f"🤝 **양쪽 블랙잭!**"
        elif player_value > 21:
            total_payout = 0
            result_text = f"💥 **버스트!**"
        elif dealer_value > 21 or player_value > dealer_value:
            multiplier = 4 if self.doubled_down else 2
            total_payout = self.bet * multiplier
            result_text = f"🎉 **승리!**"
        elif player_value == dealer_value:
            multiplier = 2 if self.doubled_down else 1
            total_payout = self.bet * multiplier
            result_text = f"🤝 **무승부!**"
        else:
            total_payout = 0
            result_text = f"😞 **패배!**"

        # Handle insurance bet
        if self.insurance_bet > 0:
            if self.dealer_blackjack:
                insurance_payout = self.insurance_bet * 3
                total_payout += insurance_payout
                result_text += f"\n💡 **보험 적중!**"
            else:
                result_text += f"\n❌ **보험 실패**"

        # Only add coins if there's actually a payout
        if total_payout > 0:
            await coins_cog.add_coins(self.user_id, interaction.guild.id, total_payout, "blackjack_win",
                                      "Blackjack payout")

        embed = await self.create_embed(final=True)

        # STANDARDIZED FIELD 3: Game Results (matching slots format)
        total_bet = self.bet * (2 if self.doubled_down else 1) + self.insurance_bet
        if total_payout > 0:
            profit = total_payout - total_bet
            result_info = f"{result_text}\n\n💰 **수익:** {total_payout:,} 코인\n"
            if profit > 0:
                result_info += f"📈 **순이익:** +{profit:,} 코인"
            else:
                result_info += f"📉 **순손실:** {profit:,} 코인"
        else:
            result_info = f"{result_text}\n\n💸 **손실:** {total_bet:,} 코인"

        embed.add_field(name="📊 게임 결과", value=result_info, inline=False)

        # STANDARDIZED FIELD 4: Balance Info
        new_balance = await coins_cog.get_user_coins(self.user_id, interaction.guild.id)
        embed.add_field(name="", value=f"🏦 **현재 잔액:** {new_balance:,} 코인", inline=False)

        # Standardized footer
        embed.set_footer(text=f"플레이어: {interaction.user.display_name} | Server: {interaction.guild.name}")

        await interaction.edit_original_response(embed=embed, view=self)

    async def end_split_game(self, interaction: discord.Interaction):
        """Handle split game end with standardized display"""
        coins_cog = self.bot.get_cog('CoinsCog')
        dealer_value = self.calculate_hand_value(self.dealer_hand)
        total_payout = 0
        results = []

        for i, hand in enumerate(self.split_hands):
            hand_value = self.calculate_hand_value(hand)

            if hand_value > 21:
                results.append(f"핸드 {i + 1}: **버스트** (손실: {self.bet:,})")
            elif dealer_value > 21 or hand_value > dealer_value:
                payout = self.bet * 2
                total_payout += payout
                results.append(f"핸드 {i + 1}: **승리** (획득: {payout:,})")
            elif hand_value == dealer_value:
                payout = self.bet
                total_payout += payout
                results.append(f"핸드 {i + 1}: **무승부** (반환: {payout:,})")
            else:
                results.append(f"핸드 {i + 1}: **패배** (손실: {self.bet:,})")

        total_bet = self.bet * 2
        net_result = total_payout - total_bet

        if total_payout > 0:
            await coins_cog.add_coins(self.user_id, interaction.guild.id, total_payout, "blackjack_split_win",
                                      "Blackjack split payout")

        embed = await self.create_split_embed(final=True)

        # STANDARDIZED FIELD 3: Game Results
        result_text = "✂️ **스플릿 결과**\n\n" + "\n".join(results)

        if net_result > 0:
            result_text += f"\n\n💰 **수익:** {total_payout:,} 코인"
            result_text += f"\n📈 **순이익:** +{net_result:,} 코인"
        elif net_result == 0:
            result_text += f"\n\n🤝 **무승부** (손익 없음)"
        else:
            result_text += f"\n\n💸 **손실:** {abs(net_result):,} 코인"

        embed.add_field(name="📊 게임 결과", value=result_text, inline=False)

        # STANDARDIZED FIELD 4: Balance Info
        new_balance = await coins_cog.get_user_coins(self.user_id, interaction.guild.id)
        embed.add_field(name="", value=f"🏦 **현재 잔액:** {new_balance:,} 코인", inline=False)

        # Standardized footer
        embed.set_footer(text=f"플레이어: {interaction.user.display_name} | Server: {interaction.guild.name}")

        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="히트", style=discord.ButtonStyle.primary, emoji="➕")
    async def hit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id or self.game_over:
            await interaction.response.send_message("❌ 권한이 없습니다!", ephemeral=True)
            return

        await interaction.response.defer()

        current_hand = self.split_hands[self.current_hand] if self.is_split else self.player_hand
        current_hand.append(self.draw_card())
        hand_value = self.calculate_hand_value(current_hand)

        if self.is_split:
            if hand_value > 21:  # Current hand busts
                if self.current_hand < len(self.split_hands) - 1:
                    self.current_hand += 1
                else:
                    while self.calculate_hand_value(self.dealer_hand) < 17:
                        self.dealer_hand.append(self.draw_card())
                    await self.end_game(interaction)
                    return

            # Disable split and double down after hitting
            for item in self.children:
                if hasattr(item, 'custom_id') and item.custom_id in ["split", "double_down"]:
                    item.disabled = True

        else:
            if hand_value > 21:
                await self.end_game(interaction)
                return

            # Disable double down and split after hitting
            for item in self.children:
                if hasattr(item, 'custom_id') and item.custom_id in ["double_down", "split"]:
                    item.disabled = True

        embed = await self.create_embed()
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="스탠드", style=discord.ButtonStyle.secondary, emoji="✋")
    async def stand_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id or self.game_over:
            await interaction.response.send_message("❌ 권한이 없습니다!", ephemeral=True)
            return

        await interaction.response.defer()

        if self.is_split:
            if self.current_hand < len(self.split_hands) - 1:
                self.current_hand += 1
                embed = await self.create_embed()
                await interaction.edit_original_response(embed=embed, view=self)
                return

        # Dealer plays (hits on soft 17)
        while self.calculate_hand_value(self.dealer_hand) < 17:
            self.dealer_hand.append(self.draw_card())

        await self.end_game(interaction)

    @discord.ui.button(label="더블다운", style=discord.ButtonStyle.success, emoji="⬆️", custom_id="double_down")
    async def double_down_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id or self.game_over:
            await interaction.response.send_message("❌ 권한이 없습니다!", ephemeral=True)
            return

        if not self.can_double_down():
            await interaction.response.send_message("❌ 더블다운할 수 없습니다!", ephemeral=True)
            return

        await interaction.response.defer()

        coins_cog = self.bot.get_cog('CoinsCog')
        if not coins_cog:
            await interaction.followup.send("❌ 코인 시스템 오류!", ephemeral=True)
            return

        # Check if user has enough for double down
        user_coins = await coins_cog.get_user_coins(self.user_id, interaction.guild.id)
        if user_coins < self.bet:
            await interaction.followup.send(f"❌ 더블다운 자금 부족! 필요: {self.bet}", ephemeral=True)
            return

        # Deduct additional bet
        if not await coins_cog.remove_coins(self.user_id, interaction.guild.id, self.bet, "blackjack_double",
                                            "Blackjack double down"):
            await interaction.followup.send("❌ 더블다운 처리 실패!", ephemeral=True)
            return

        self.doubled_down = True

        # Hit exactly one card and stand
        current_hand = self.split_hands[self.current_hand] if self.is_split else self.player_hand
        current_hand.append(self.draw_card())
        hand_value = self.calculate_hand_value(current_hand)

        if self.is_split:
            if self.current_hand < len(self.split_hands) - 1:
                self.current_hand += 1
                embed = await self.create_embed()
                await interaction.edit_original_response(embed=embed, view=self)
                return

        if not self.is_split and hand_value > 21:
            await self.end_game(interaction)
        else:
            # Dealer plays
            while self.calculate_hand_value(self.dealer_hand) < 17:
                self.dealer_hand.append(self.draw_card())
            await self.end_game(interaction)

    @discord.ui.button(label="스플릿", style=discord.ButtonStyle.danger, emoji="✂️", custom_id="split")
    async def split_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id or self.game_over:
            await interaction.response.send_message("❌ 권한이 없습니다!", ephemeral=True)
            return

        if not self.can_split():
            await interaction.response.send_message("❌ 스플릿할 수 없습니다!", ephemeral=True)
            return

        await interaction.response.defer()

        coins_cog = self.bot.get_cog('CoinsCog')
        if not coins_cog:
            return

        # Check if user has enough for split
        user_coins = await coins_cog.get_user_coins(self.user_id, interaction.guild.id)
        if user_coins < self.bet:
            await interaction.followup.send(f"❌ 스플릿 자금 부족! 필요: {self.bet}", ephemeral=True)
            return

        # Deduct additional bet for split
        if not await coins_cog.remove_coins(self.user_id, interaction.guild.id, self.bet, "blackjack_split",
                                            "Blackjack split"):
            await interaction.followup.send("❌ 스플릿 처리 실패!", ephemeral=True)
            return

        # Create split hands
        self.is_split = True
        self.split_hands = [[self.player_hand[0]], [self.player_hand[1]]]

        # Deal one card to each hand
        self.split_hands[0].append(self.draw_card())
        self.split_hands[1].append(self.draw_card())

        self.current_hand = 0

        # Disable split button after splitting
        button.disabled = True

        embed = await self.create_embed()
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="보험", style=discord.ButtonStyle.secondary, emoji="🛡️", custom_id="insurance")
    async def insurance_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id or self.game_over:
            await interaction.response.send_message("❌ 권한이 없습니다!", ephemeral=True)
            return

        if not self.can_insure:
            await interaction.response.send_message("❌ 딜러의 오픈 카드가 에이스가 아닙니다!", ephemeral=True)
            return

        if self.insurance_bet > 0:
            await interaction.response.send_message("❌ 이미 보험에 가입했습니다!", ephemeral=True)
            return

        await interaction.response.defer()

        coins_cog = self.bot.get_cog('CoinsCog')
        if not coins_cog:
            return

        insurance_amount = self.bet // 2
        user_coins = await coins_cog.get_user_coins(self.user_id, interaction.guild.id)

        if user_coins < insurance_amount:
            await interaction.followup.send(f"❌ 보험료 부족! 필요: {insurance_amount}", ephemeral=True)
            return

        if await coins_cog.remove_coins(self.user_id, interaction.guild.id, insurance_amount, "blackjack_insurance",
                                        "Blackjack insurance"):
            self.insurance_bet = insurance_amount
            button.disabled = True

            embed = await self.create_embed()
            await interaction.edit_original_response(embed=embed, view=self)


class BlackjackCog(commands.Cog):
    """Professional Blackjack with advanced features - Multi-server aware"""

    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("블랙잭")
        self.logger.info("블랙잭 시스템이 초기화되었습니다.")

    @app_commands.command(name="블랙잭", description="전문적인 블랙잭 게임 (더블다운, 보험, 스플릿 포함)")
    @app_commands.describe(bet="베팅할 코인 수")
    async def blackjack(self, interaction: discord.Interaction, bet: int):
        # Check if casino games are enabled for this server
        if not interaction.guild or not is_feature_enabled(interaction.guild.id, 'casino_games'):
            await interaction.response.send_message("❌ 이 서버에서는 카지노 게임이 비활성화되어 있습니다!", ephemeral=True)
            return

        # Get server-specific bet limits
        min_bet = get_server_setting(interaction.guild.id, 'blackjack_min_bet', 20)
        max_bet = get_server_setting(interaction.guild.id, 'blackjack_max_bet', 200)

        if bet < min_bet or bet > max_bet:
            await interaction.response.send_message(f"❌ 베팅은 {min_bet}~{max_bet:,} 코인 사이만 가능합니다.", ephemeral=True)
            return

        # Validate using casino base
        casino_base = self.bot.get_cog('CasinoBaseCog')
        if casino_base:
            can_start, error_msg = await casino_base.validate_game_start(
                interaction, "blackjack", bet, min_bet, max_bet
            )
            if not can_start:
                await interaction.response.send_message(error_msg, ephemeral=True)
                return

        coins_cog = self.bot.get_cog('CoinsCog')
        if not coins_cog:
            await interaction.response.send_message("❌ 코인 시스템을 찾을 수 없습니다!", ephemeral=True)
            return

        user_coins = await coins_cog.get_user_coins(interaction.user.id, interaction.guild.id)
        if user_coins < bet:
            await interaction.response.send_message(f"❌ 코인 부족! 필요: {bet:,}, 보유: {user_coins:,}", ephemeral=True)
            return

        # Deduct initial bet
        if not await coins_cog.remove_coins(interaction.user.id, interaction.guild.id, bet, "blackjack_bet",
                                            "Blackjack initial bet"):
            await interaction.response.send_message("❌ 베팅 처리 실패!", ephemeral=True)
            return

        view = BlackjackView(self.bot, interaction.user.id, bet)

        # Disable buttons based on game state
        for item in view.children:
            if hasattr(item, 'custom_id'):
                if item.custom_id == "insurance" and not view.can_insure:
                    item.disabled = True
                elif item.custom_id == "split" and not view.can_split():
                    item.disabled = True
                elif view.game_over:  # Disable all if blackjack
                    item.disabled = True

        embed = await view.create_embed()

        # Handle immediate blackjack payout
        if view.player_blackjack:
            await view.end_game(interaction)
            return

        # Add strategy hints as a separate field
        if not view.game_over:
            player_val = view.calculate_hand_value(view.player_hand)
            dealer_up = view.dealer_hand[0]['rank']

            hints = []
            if view.can_double_down():
                if player_val == 11:
                    hints.append("💡 11에서 더블다운 추천")
                elif player_val == 10 and dealer_up not in ['10', 'J', 'Q', 'K', 'A']:
                    hints.append("💡 더블다운 고려해보세요")

            if view.can_split():
                hints.append("💡 스플릿 가능")

            if player_val <= 11:
                hints.append("🃏 버스트 불가능 - 히트 안전")
            elif player_val >= 17:
                hints.append("⚠️ 높은 수치 - 스탠드 고려")

            if hints:
                embed.add_field(name="🎯 전략 힌트", value="\n".join(hints), inline=False)

        await interaction.response.send_message(embed=embed, view=view)
        self.logger.info(
            f"{interaction.user}가 {bet} 코인으로 블랙잭 시작",
            extra={'guild_id': interaction.guild.id}
        )


async def setup(bot):
    await bot.add_cog(BlackjackCog(bot))