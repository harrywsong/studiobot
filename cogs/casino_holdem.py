# cogs/casino_holdem.py - Texas Hold'em Poker game (FIXED)
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import random
from typing import Dict, List, Optional, Tuple
from enum import Enum

from utils.logger import get_logger
from utils.config import (
    is_feature_enabled,
    is_server_configured
)


class Suit(Enum):
    HEARTS = "♥️"
    DIAMONDS = "♦️"
    CLUBS = "♣️"
    SPADES = "♠️"


class Card:
    """Represents a playing card"""

    def __init__(self, rank: int, suit: Suit):
        self.rank = rank  # 2-14 (11=J, 12=Q, 13=K, 14=A)
        self.suit = suit

    def __str__(self):
        rank_names = {11: "J", 12: "Q", 13: "K", 14: "A"}
        rank_str = rank_names.get(self.rank, str(self.rank))
        return f"{rank_str}{self.suit.value}"

    def __eq__(self, other):
        return self.rank == other.rank and self.suit == other.suit

    def __lt__(self, other):
        return self.rank < other.rank


class Deck:
    """Standard 52-card deck"""

    def __init__(self):
        self.cards = []
        self.reset()

    def reset(self):
        """Reset and shuffle deck"""
        self.cards = []
        for suit in Suit:
            for rank in range(2, 15):  # 2-14 (A)
                self.cards.append(Card(rank, suit))
        random.shuffle(self.cards)

    def deal(self) -> Card:
        """Deal one card"""
        return self.cards.pop() if self.cards else None


class HandRank(Enum):
    HIGH_CARD = 1
    PAIR = 2
    TWO_PAIR = 3
    THREE_KIND = 4
    STRAIGHT = 5
    FLUSH = 6
    FULL_HOUSE = 7
    FOUR_KIND = 8
    STRAIGHT_FLUSH = 9
    ROYAL_FLUSH = 10


class PokerHand:
    """Evaluate poker hands"""

    @staticmethod
    def evaluate_hand(cards: List[Card]) -> Tuple[HandRank, List[int]]:
        """Evaluate 7 cards and return best 5-card hand rank and tiebreakers"""
        if len(cards) != 7:
            raise ValueError("Must have exactly 7 cards")

        # Get all possible 5-card combinations
        from itertools import combinations
        best_rank = HandRank.HIGH_CARD
        best_tiebreakers = []

        for combo in combinations(cards, 5):
            rank, tiebreakers = PokerHand._evaluate_5_cards(list(combo))
            if rank.value > best_rank.value or (rank == best_rank and tiebreakers > best_tiebreakers):
                best_rank = rank
                best_tiebreakers = tiebreakers

        return best_rank, best_tiebreakers

    @staticmethod
    def _evaluate_5_cards(cards: List[Card]) -> Tuple[HandRank, List[int]]:
        """Evaluate exactly 5 cards"""
        cards.sort(key=lambda x: x.rank, reverse=True)
        ranks = [card.rank for card in cards]
        suits = [card.suit for card in cards]

        # Count ranks
        rank_counts = {}
        for rank in ranks:
            rank_counts[rank] = rank_counts.get(rank, 0) + 1

        counts = sorted(rank_counts.values(), reverse=True)
        unique_ranks = sorted(rank_counts.keys(), reverse=True)

        # Check for flush
        is_flush = len(set(suits)) == 1

        # Check for straight
        is_straight = False
        straight_high = 0
        if ranks == [14, 5, 4, 3, 2]:  # A-5 straight (wheel)
            is_straight = True
            straight_high = 5
        elif all(ranks[i] - ranks[i + 1] == 1 for i in range(4)):
            is_straight = True
            straight_high = ranks[0]

        # Determine hand rank
        if is_straight and is_flush:
            if straight_high == 14:
                return HandRank.ROYAL_FLUSH, [14]
            else:
                return HandRank.STRAIGHT_FLUSH, [straight_high]
        elif counts == [4, 1]:
            four_kind = [r for r, c in rank_counts.items() if c == 4][0]
            kicker = [r for r, c in rank_counts.items() if c == 1][0]
            return HandRank.FOUR_KIND, [four_kind, kicker]
        elif counts == [3, 2]:
            trip = [r for r, c in rank_counts.items() if c == 3][0]
            pair = [r for r, c in rank_counts.items() if c == 2][0]
            return HandRank.FULL_HOUSE, [trip, pair]
        elif is_flush:
            return HandRank.FLUSH, ranks
        elif is_straight:
            return HandRank.STRAIGHT, [straight_high]
        elif counts == [3, 1, 1]:
            trip = [r for r, c in rank_counts.items() if c == 3][0]
            kickers = sorted([r for r, c in rank_counts.items() if c == 1], reverse=True)
            return HandRank.THREE_KIND, [trip] + kickers
        elif counts == [2, 2, 1]:
            pairs = sorted([r for r, c in rank_counts.items() if c == 2], reverse=True)
            kicker = [r for r, c in rank_counts.items() if c == 1][0]
            return HandRank.TWO_PAIR, pairs + [kicker]
        elif counts == [2, 1, 1, 1]:
            pair = [r for r, c in rank_counts.items() if c == 2][0]
            kickers = sorted([r for r, c in rank_counts.items() if c == 1], reverse=True)
            return HandRank.PAIR, [pair] + kickers
        else:
            return HandRank.HIGH_CARD, ranks


class HoldemPlayer:
    """Represents a poker player"""

    def __init__(self, user_id: int, username: str, chips: int):
        self.user_id = user_id
        self.username = username
        self.chips = chips
        self.hole_cards = []
        self.current_bet = 0
        self.total_bet = 0
        self.folded = False
        self.all_in = False
        self.acted_this_round = False


class HoldemGame:
    """Texas Hold'em game logic"""

    def __init__(self, bot, guild_id: int, channel_id: int, buy_in: int):
        self.bot = bot
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.buy_in = buy_in
        self.players: List[HoldemPlayer] = []
        self.deck = Deck()
        self.community_cards = []
        self.pot = 0
        self.current_bet = 0
        self.dealer_pos = 0
        self.current_player = 0
        self.betting_round = 0  # 0=preflop, 1=flop, 2=turn, 3=river
        self.game_over = False
        self.winners = []
        self.small_blind = max(1, buy_in // 100)  # 1% of buy-in
        self.big_blind = self.small_blind * 2

    def add_player(self, user_id: int, username: str) -> bool:
        """Add player to game"""
        if len(self.players) < 8 and not any(p.user_id == user_id for p in self.players):
            player = HoldemPlayer(user_id, username, self.buy_in)
            self.players.append(player)
            return True
        return False

    def remove_player(self, user_id: int) -> bool:
        """Remove player from game"""
        self.players = [p for p in self.players if p.user_id != user_id]
        return True

    def start_hand(self):
        """Start a new hand"""
        if len(self.players) < 2:
            return False

        # Reset for new hand
        self.deck.reset()
        self.community_cards = []
        self.pot = 0
        self.current_bet = 0
        self.betting_round = 0
        self.game_over = False

        # Remove players with no chips
        self.players = [p for p in self.players if p.chips > 0]

        if len(self.players) < 2:
            return False

        # Reset player states
        for player in self.players:
            player.hole_cards = []
            player.current_bet = 0
            player.total_bet = 0
            player.folded = False
            player.all_in = False
            player.acted_this_round = False

        # Deal hole cards
        for _ in range(2):
            for player in self.players:
                player.hole_cards.append(self.deck.deal())

        # Post blinds
        self.post_blinds()

        # Set first player to act (after big blind)
        self.current_player = (self.dealer_pos + 3) % len(self.players)
        if len(self.players) == 2:
            self.current_player = self.dealer_pos  # Heads up: dealer acts first preflop

        return True

    def post_blinds(self):
        """Post small and big blinds"""
        if len(self.players) < 2:
            return

        small_blind_pos = (self.dealer_pos + 1) % len(self.players)
        big_blind_pos = (self.dealer_pos + 2) % len(self.players)

        # In heads-up, dealer posts small blind
        if len(self.players) == 2:
            small_blind_pos = self.dealer_pos
            big_blind_pos = (self.dealer_pos + 1) % len(self.players)

        # Small blind
        sb_player = self.players[small_blind_pos]
        sb_amount = min(self.small_blind, sb_player.chips)
        sb_player.chips -= sb_amount
        sb_player.current_bet = sb_amount
        sb_player.total_bet = sb_amount
        self.pot += sb_amount

        # Big blind
        bb_player = self.players[big_blind_pos]
        bb_amount = min(self.big_blind, bb_player.chips)
        bb_player.chips -= bb_amount
        bb_player.current_bet = bb_amount
        bb_player.total_bet = bb_amount
        self.pot += bb_amount
        self.current_bet = bb_amount

        # Mark all-in if necessary
        if sb_player.chips == 0:
            sb_player.all_in = True
        if bb_player.chips == 0:
            bb_player.all_in = True

    def can_act(self, player_idx: int) -> bool:
        """Check if player can act"""
        if player_idx >= len(self.players):
            return False
        player = self.players[player_idx]
        return not player.folded and not player.all_in

    def get_valid_actions(self, player_idx: int) -> List[str]:
        """Get valid actions for player"""
        if not self.can_act(player_idx):
            return []

        player = self.players[player_idx]
        actions = []

        # Can always fold (unless all-in)
        if not player.all_in:
            actions.append("fold")

        # Check/call options
        to_call = self.current_bet - player.current_bet
        if to_call == 0:
            actions.append("check")
        elif to_call > 0 and player.chips >= to_call:
            actions.append("call")

        # Raise/bet options
        min_raise = max(self.big_blind, self.current_bet - player.current_bet + self.big_blind)
        if player.chips >= min_raise:
            actions.append("raise")

        # All-in
        if player.chips > 0:
            actions.append("allin")

        return actions

    def make_action(self, player_idx: int, action: str, amount: int = 0) -> bool:
        """Process player action"""
        if not self.can_act(player_idx):
            return False

        player = self.players[player_idx]
        valid_actions = self.get_valid_actions(player_idx)

        if action not in valid_actions:
            return False

        if action == "fold":
            player.folded = True
        elif action == "check":
            pass  # No chips change
        elif action == "call":
            to_call = min(self.current_bet - player.current_bet, player.chips)
            player.chips -= to_call
            player.current_bet += to_call
            player.total_bet += to_call
            self.pot += to_call
            if player.chips == 0:
                player.all_in = True
        elif action == "raise":
            # For simplicity, use minimum raise
            min_raise_amount = max(self.big_blind, self.current_bet - player.current_bet + self.big_blind)
            actual_raise = min(min_raise_amount, player.chips)

            player.chips -= actual_raise
            player.current_bet += actual_raise
            player.total_bet += actual_raise
            self.pot += actual_raise
            self.current_bet = player.current_bet

            if player.chips == 0:
                player.all_in = True
        elif action == "allin":
            amount = player.chips
            player.chips = 0
            player.current_bet += amount
            player.total_bet += amount
            self.pot += amount
            self.current_bet = max(self.current_bet, player.current_bet)
            player.all_in = True

        player.acted_this_round = True
        return True

    def is_betting_round_complete(self) -> bool:
        """Check if current betting round is complete"""
        active_players = [p for p in self.players if not p.folded]

        if len(active_players) <= 1:
            return True

        # All active players must have acted and have equal bets (or be all-in)
        for player in active_players:
            if not player.acted_this_round:
                return False
            if not player.all_in and player.current_bet != self.current_bet:
                return False

        return True

    def advance_betting_round(self):
        """Move to next betting round"""
        # Reset for next round
        for player in self.players:
            player.current_bet = 0
            player.acted_this_round = False

        self.current_bet = 0
        self.betting_round += 1

        # Deal community cards
        if self.betting_round == 1:  # Flop
            for _ in range(3):
                self.community_cards.append(self.deck.deal())
        elif self.betting_round in [2, 3]:  # Turn, River
            self.community_cards.append(self.deck.deal())

        # Set first active player to act (starting from dealer+1)
        self.current_player = self.get_next_active_player(self.dealer_pos)

    def get_next_active_player(self, start_pos: int) -> int:
        """Get next player who can act"""
        for i in range(1, len(self.players) + 1):
            pos = (start_pos + i) % len(self.players)
            if self.can_act(pos):
                return pos
        return -1

    def determine_winners(self):
        """Determine winners and distribute pot"""
        active_players = [p for p in self.players if not p.folded]

        if len(active_players) == 1:
            # Only one player left
            winner = active_players[0]
            winner.chips += self.pot
            self.winners = [winner]
            return

        # Evaluate hands
        player_hands = []
        for player in active_players:
            all_cards = player.hole_cards + self.community_cards
            hand_rank, tiebreakers = PokerHand.evaluate_hand(all_cards)
            player_hands.append((player, hand_rank, tiebreakers))

        # Sort by hand strength (best first)
        player_hands.sort(key=lambda x: (x[1].value, x[2]), reverse=True)

        # Find winners (players with same best hand)
        best_rank = player_hands[0][1]
        best_tiebreakers = player_hands[0][2]

        winners = []
        for player, rank, tiebreakers in player_hands:
            if rank == best_rank and tiebreakers == best_tiebreakers:
                winners.append(player)
            else:
                break

        # Distribute pot
        pot_share = self.pot // len(winners)
        remainder = self.pot % len(winners)

        for i, winner in enumerate(winners):
            share = pot_share + (1 if i < remainder else 0)
            winner.chips += share

        self.winners = winners


class HoldemView(discord.ui.View):
    """Interactive Texas Hold'em game view"""

    def __init__(self, bot, guild_id: int, channel_id: int, buy_in: int):
        super().__init__(timeout=300)  # 5 minutes
        self.bot = bot
        self.game = HoldemGame(bot, guild_id, channel_id, buy_in)
        self.join_phase = True
        self.waiting_for_action = False
        self.current_message = None

    async def show_hole_cards(self):
        """Send hole cards privately to each player"""
        for player in self.game.players:
            if player.hole_cards:
                cards_str = " ".join(str(card) for card in player.hole_cards)
                embed = discord.Embed(
                    title="🃏 Your Hole Cards",
                    description=f"**Your Cards:** {cards_str}",
                    color=discord.Color.blue()
                )
                embed.add_field(
                    name="🔒 Note",
                    value="Keep these cards secret! Only you can see them.",
                    inline=False
                )

                try:
                    user = self.bot.get_user(player.user_id)
                    if user:
                        await user.send(embed=embed)
                except discord.Forbidden:
                    # If we can't DM, try to mention in channel
                    pass

    async def start_game(self, interaction: discord.Interaction):
        """Start the poker game"""
        if len(self.game.players) < 2:
            await interaction.response.send_message("❌ 최소 2명의 플레이어가 필요합니다!", ephemeral=True)
            return

        self.join_phase = False
        success = self.game.start_hand()

        if not success:
            await interaction.response.send_message("❌ 게임 시작에 실패했습니다!", ephemeral=True)
            return

        # Show hole cards to players privately
        await self.show_hole_cards()

        # Update buttons for game actions
        self.clear_items()
        self.add_action_buttons()

        embed = self.create_game_embed()
        await interaction.response.edit_message(embed=embed, view=self)

        # Start action handling
        await self.handle_player_turn()

    def add_action_buttons(self):
        """Add poker action buttons"""
        self.add_item(ActionButton("fold", "폴드", discord.ButtonStyle.red, "❌"))
        self.add_item(ActionButton("check", "체크", discord.ButtonStyle.gray, "✅"))
        self.add_item(ActionButton("call", "콜", discord.ButtonStyle.green, "📞"))
        self.add_item(ActionButton("raise", "레이즈", discord.ButtonStyle.primary, "⬆️"))
        self.add_item(ActionButton("allin", "올인", discord.ButtonStyle.danger, "💰"))

    async def handle_player_turn(self):
        """Handle current player's turn with timer"""
        while not self.game.game_over and not self.join_phase:
            # Check if betting round is complete
            if self.game.is_betting_round_complete():
                if self.game.betting_round >= 3:  # River completed
                    self.game.determine_winners()
                    self.game.game_over = True
                    await self.show_results()
                    return
                else:
                    self.game.advance_betting_round()
                    # Update display after advancing round
                    embed = self.create_game_embed()
                    try:
                        if self.current_message:
                            await self.current_message.edit(embed=embed, view=self)
                    except:
                        pass

            # Check if only one player left
            active_players = [p for p in self.game.players if not p.folded]
            if len(active_players) <= 1:
                if active_players:
                    self.game.winners = active_players
                    active_players[0].chips += self.game.pot
                self.game.game_over = True
                await self.show_results()
                return

            if self.game.current_player == -1:
                break

            # Wait for current player action (30 seconds)
            self.waiting_for_action = True

            for _ in range(30):  # 30 second timer
                if not self.waiting_for_action or self.game.game_over:
                    break
                await asyncio.sleep(1)

            # Auto-fold if no action taken
            if self.waiting_for_action and not self.game.game_over:
                self.game.make_action(self.game.current_player, "fold")
                self.waiting_for_action = False

                # Move to next player
                self.game.current_player = self.game.get_next_active_player(self.game.current_player)

    async def show_results(self):
        """Show final results"""
        self.clear_items()

        # Handle payouts
        coins_cog = self.bot.get_cog('CoinsCog')
        if coins_cog:
            for player in self.game.players:
                if player.chips > 0:
                    # Return remaining chips
                    await coins_cog.add_coins(
                        player.user_id,
                        self.game.guild_id,
                        player.chips,
                        "holdem_payout",
                        f"텍사스 홀덤 정산 ({player.chips}칩)"
                    )

        embed = self.create_results_embed()
        if self.current_message:
            try:
                await self.current_message.edit(embed=embed, view=self)
            except:
                pass

    def create_game_embed(self) -> discord.Embed:
        """Create game status embed"""
        if self.join_phase:
            title = "🃏 텍사스 홀덤 - 플레이어 모집"
            color = discord.Color.blue()
            description = f"**바이인:** {self.game.buy_in:,}코인\n**플레이어:** {len(self.game.players)}/8\n\n'게임 참가' 버튼을 눌러 참여하세요!"

            embed = discord.Embed(title=title, description=description, color=color)

            if self.game.players:
                player_list = []
                for player in self.game.players:
                    player_list.append(f"🎰 {player.username}")
                embed.add_field(name="👥 참가자", value="\n".join(player_list), inline=False)

            embed.add_field(
                name="📋 게임 규칙",
                value=f"• 바이인: {self.game.buy_in:,}코인\n• 스몰블라인드: {self.game.small_blind}칩\n• 빅블라인드: {self.game.big_blind}칩\n• 최고 핸드가 팟을 가져감\n• 칩이 떨어지면 탈락\n• 홀카드는 개인 메시지로 전송됩니다",
                inline=False
            )
        else:
            title = "🃏 텍사스 홀덤 - 진행 중"
            color = discord.Color.green()

            # Game state info
            round_names = ["프리플롭", "플롭", "턴", "리버"]
            round_name = round_names[min(self.game.betting_round, 3)]

            current_player = None
            if 0 <= self.game.current_player < len(self.game.players):
                current_player = self.game.players[self.game.current_player]

            description = f"**라운드:** {round_name}\n**팟:** {self.game.pot:,}칩\n**현재 베팅:** {self.game.current_bet}칩"

            if current_player and not self.game.game_over:
                description += f"\n\n🎯 **현재 차례:** {current_player.username}"

            embed = discord.Embed(title=title, description=description, color=color)

            # Community cards
            if self.game.community_cards:
                cards_str = " ".join(str(card) for card in self.game.community_cards)
                embed.add_field(name="🃏 커뮤니티 카드", value=cards_str, inline=False)

            # Player info
            player_info = []
            for i, player in enumerate(self.game.players):
                status = ""
                if player.folded:
                    status = "폴드"
                elif player.all_in:
                    status = "올인"
                elif i == self.game.current_player:
                    status = "👈"

                player_info.append(f"{player.username}: {player.chips}칩 (베팅:{player.current_bet}) {status}")

            embed.add_field(name="👥 플레이어 현황", value="\n".join(player_info), inline=False)

            # Note about hole cards
            embed.add_field(
                name="🔒 참고",
                value="홀카드는 개인 메시지로 확인하세요!",
                inline=False
            )

        return embed

    def create_results_embed(self) -> discord.Embed:
        """Create results embed"""
        title = "🏆 텍사스 홀덤 결과"
        color = discord.Color.gold()

        description = f"**팟 크기:** {self.game.pot:,}칩"

        embed = discord.Embed(title=title, description=description, color=color)

        # Winners
        if self.game.winners:
            winner_names = [w.username for w in self.game.winners]
            embed.add_field(name="🥇 승자", value="\n".join(winner_names), inline=False)

        # Final community cards
        if self.game.community_cards:
            cards_str = " ".join(str(card) for card in self.game.community_cards)
            embed.add_field(name="🃏 최종 커뮤니티 카드", value=cards_str, inline=False)

        # Show all players' hole cards in results
        hole_cards_info = []
        for player in self.game.players:
            if player.hole_cards:
                cards_str = " ".join(str(card) for card in player.hole_cards)
                hole_cards_info.append(f"{player.username}: {cards_str}")

        if hole_cards_info:
            embed.add_field(name="🔍 모든 플레이어 홀카드", value="\n".join(hole_cards_info), inline=False)

        # Final chip counts
        chip_info = []
        for player in self.game.players:
            chip_info.append(f"{player.username}: {player.chips}칩")
        embed.add_field(name="💰 최종 칩 현황", value="\n".join(chip_info), inline=False)

        return embed

    @discord.ui.button(label="🎰 게임 참가", style=discord.ButtonStyle.green)
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.join_phase:
            await interaction.response.send_message("❌ 게임이 이미 시작되었습니다!", ephemeral=True)
            return

        # Validate player can afford buy-in
        casino_base = self.bot.get_cog('CasinoBaseCog')
        if casino_base:
            can_start, error_msg = await casino_base.validate_game_start(
                interaction, "holdem", self.game.buy_in, self.game.buy_in, self.game.buy_in
            )
            if not can_start:
                await interaction.response.send_message(error_msg, ephemeral=True)
                return

        # Check if already joined
        if any(p.user_id == interaction.user.id for p in self.game.players):
            await interaction.response.send_message("❌ 이미 게임에 참가하셨습니다!", ephemeral=True)
            return

        # Add player
        if not self.game.add_player(interaction.user.id, interaction.user.display_name):
            await interaction.response.send_message("❌ 게임이 가득 찼습니다! (최대 8명)", ephemeral=True)
            return

        # Deduct buy-in
        coins_cog = self.bot.get_cog('CoinsCog')
        success = await coins_cog.remove_coins(
            interaction.user.id,
            interaction.guild.id,
            self.game.buy_in,
            "holdem_buyin",
            f"텍사스 홀덤 바이인 ({self.game.buy_in}코인)"
        )

        if not success:
            self.game.remove_player(interaction.user.id)
            await interaction.response.send_message("❌ 바이인 처리에 실패했습니다!", ephemeral=True)
            return

        embed = self.create_game_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🚀 게임 시작", style=discord.ButtonStyle.primary)
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.start_game(interaction)


class ActionButton(discord.ui.Button):
    """Poker action button"""

    def __init__(self, action: str, label: str, style: discord.ButtonStyle, emoji: str = None):
        super().__init__(label=label, style=style, emoji=emoji)
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        game = view.game

        # Find player
        player_idx = -1
        for i, player in enumerate(game.players):
            if player.user_id == interaction.user.id:
                player_idx = i
                break

        if player_idx == -1:
            await interaction.response.send_message("❌ 이 게임에 참가하지 않았습니다!", ephemeral=True)
            return

        if player_idx != game.current_player:
            await interaction.response.send_message("❌ 지금은 당신의 차례가 아닙니다!", ephemeral=True)
            return

        # Check if action is valid
        valid_actions = game.get_valid_actions(player_idx)
        if self.action not in valid_actions:
            await interaction.response.send_message("❌ 유효하지 않은 액션입니다!", ephemeral=True)
            return

        # Handle raise action (need amount)
        amount = 0
        if self.action == "raise":
            # For simplicity, use minimum raise
            min_raise = max(game.big_blind, game.current_bet - game.players[player_idx].current_bet + game.big_blind)
            amount = min_raise

        # Make the action
        success = game.make_action(player_idx, self.action, amount)
        if not success:
            await interaction.response.send_message("❌ 액션 처리에 실패했습니다!", ephemeral=True)
            return

        view.waiting_for_action = False

        # Move to next player
        game.current_player = game.get_next_active_player(game.current_player)

        embed = view.create_game_embed()
        await interaction.response.edit_message(embed=embed, view=view)

        # The handle_player_turn loop will continue automatically


class HoldemCog(commands.Cog):
    """Texas Hold'em Poker game"""

    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("텍사스홀덤")
        self.active_games: Dict[int, HoldemView] = {}  # channel_id -> game
        self.logger.info("텍사스 홀덤 게임 시스템이 초기화되었습니다.")

    @app_commands.command(name="홀덤", description="텍사스 홀덤 포커 게임을 시작합니다")
    @app_commands.describe(buy_in="바이인 금액 (100-1000코인)")
    async def holdem(self, interaction: discord.Interaction, buy_in: int = 100):
        try:
            # Validate game using casino base
            casino_base = self.bot.get_cog('CasinoBaseCog')
            if casino_base:
                can_start, error_msg = await casino_base.validate_game_start(
                    interaction, "holdem", buy_in, 100, 1000
                )
                if not can_start:
                    await interaction.response.send_message(error_msg, ephemeral=True)
                    return

            channel_id = interaction.channel.id

            # Check for existing game
            if channel_id in self.active_games:
                existing = self.active_games[channel_id]
                if existing.join_phase:
                    await interaction.response.send_message("❌ 이 채널에서 이미 홀덤 게임 모집 중입니다!", ephemeral=True)
                    return
                elif not existing.game.game_over:
                    await interaction.response.send_message("❌ 이 채널에서 홀덤 게임이 진행 중입니다!", ephemeral=True)
                    return

            # Create new game
            game_view = HoldemView(self.bot, interaction.guild.id, channel_id, buy_in)
            self.active_games[channel_id] = game_view

            embed = game_view.create_game_embed()
            await interaction.response.send_message(embed=embed, view=game_view)

            # Store message for later updates
            game_view.current_message = await interaction.original_response()

            self.logger.info(
                f"{interaction.user}가 {buy_in}코인 바이인으로 텍사스 홀덤을 시작했습니다",
                extra={'guild_id': interaction.guild.id}
            )

        except Exception as e:
            self.logger.error(f"Holdem command error: {e}", exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ 게임 시작 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ 게임 시작 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.", ephemeral=True)
            except:
                pass


async def setup(bot):
    await bot.add_cog(HoldemCog(bot))