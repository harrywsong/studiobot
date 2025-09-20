# cogs/casino_holdem.py - Texas Hold'em Poker game with fixed hand evaluation
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import random
from typing import Dict, List, Optional, Tuple
from enum import Enum
from itertools import combinations

from utils.logger import get_logger
from utils.config import (
    is_feature_enabled,
    is_server_configured
)
from cogs.coins import check_user_casino_eligibility


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
    """Fixed poker hand evaluation"""

    @staticmethod
    def evaluate_hand(cards: List[Card]) -> Tuple[HandRank, List[int]]:
        """Evaluate 7 cards and return best 5-card hand rank and tiebreakers"""
        if len(cards) != 7:
            raise ValueError("Must have exactly 7 cards")

        best_rank = HandRank.HIGH_CARD
        best_tiebreakers = []

        # Get all possible 5-card combinations
        for combo in combinations(cards, 5):
            rank, tiebreakers = PokerHand._evaluate_5_cards(list(combo))

            # Compare hands - higher rank wins, or same rank with better tiebreakers
            if (rank.value > best_rank.value or
                    (rank == best_rank and PokerHand._compare_tiebreakers(tiebreakers, best_tiebreakers) > 0)):
                best_rank = rank
                best_tiebreakers = tiebreakers

        return best_rank, best_tiebreakers

    @staticmethod
    def _compare_tiebreakers(tb1: List[int], tb2: List[int]) -> int:
        """Compare two tiebreaker lists. Returns 1 if tb1 > tb2, -1 if tb1 < tb2, 0 if equal"""
        for i in range(min(len(tb1), len(tb2))):
            if tb1[i] > tb2[i]:
                return 1
            elif tb1[i] < tb2[i]:
                return -1
        return 0

    @staticmethod
    def _evaluate_5_cards(cards: List[Card]) -> Tuple[HandRank, List[int]]:
        """Evaluate exactly 5 cards with fixed logic"""
        # Sort cards by rank (highest first)
        cards.sort(key=lambda x: x.rank, reverse=True)
        ranks = [card.rank for card in cards]
        suits = [card.suit for card in cards]

        # Count each rank
        rank_counts = {}
        for rank in ranks:
            rank_counts[rank] = rank_counts.get(rank, 0) + 1

        # Get counts in descending order
        counts = sorted(rank_counts.values(), reverse=True)

        # Get ranks sorted by count (descending), then by rank value (descending)
        ranks_by_count = sorted(rank_counts.keys(), key=lambda r: (rank_counts[r], r), reverse=True)

        # Check for flush
        is_flush = len(set(suits)) == 1

        # Check for straight
        is_straight, straight_high = PokerHand._check_straight(ranks)

        # Determine hand rank and tiebreakers
        if is_straight and is_flush:
            if straight_high == 14 and ranks == [14, 13, 12, 11, 10]:  # Royal flush
                return HandRank.ROYAL_FLUSH, [14]
            else:
                return HandRank.STRAIGHT_FLUSH, [straight_high]

        elif counts == [4, 1]:  # Four of a kind
            four_kind = ranks_by_count[0]  # The rank with 4 cards
            kicker = ranks_by_count[1]  # The rank with 1 card
            return HandRank.FOUR_KIND, [four_kind, kicker]

        elif counts == [3, 2]:  # Full house
            three_kind = ranks_by_count[0]  # The rank with 3 cards
            pair = ranks_by_count[1]  # The rank with 2 cards
            return HandRank.FULL_HOUSE, [three_kind, pair]

        elif is_flush:
            return HandRank.FLUSH, ranks  # All 5 ranks as tiebreakers

        elif is_straight:
            return HandRank.STRAIGHT, [straight_high]

        elif counts == [3, 1, 1]:  # Three of a kind
            three_kind = ranks_by_count[0]
            kickers = sorted(ranks_by_count[1:3], reverse=True)
            return HandRank.THREE_KIND, [three_kind] + kickers

        elif counts == [2, 2, 1]:  # Two pair
            pairs = sorted(ranks_by_count[0:2], reverse=True)
            kicker = ranks_by_count[2]
            return HandRank.TWO_PAIR, pairs + [kicker]

        elif counts == [2, 1, 1, 1]:  # One pair
            pair = ranks_by_count[0]
            kickers = sorted(ranks_by_count[1:4], reverse=True)
            return HandRank.PAIR, [pair] + kickers

        else:  # High card
            return HandRank.HIGH_CARD, ranks

    @staticmethod
    def _check_straight(ranks: List[int]) -> Tuple[bool, int]:
        """Check if ranks form a straight, return (is_straight, high_card)"""
        # Remove duplicates and sort
        unique_ranks = sorted(set(ranks), reverse=True)

        # Check for A-5 straight (wheel)
        if unique_ranks == [14, 5, 4, 3, 2]:
            return True, 5

        # Check for normal straight
        if len(unique_ranks) >= 5:
            for i in range(len(unique_ranks) - 4):
                if all(unique_ranks[i] - unique_ranks[i + j] == j for j in range(5)):
                    return True, unique_ranks[i]

        return False, 0

    @staticmethod
    def compare_hands(hand1_data: Tuple[HandRank, List[int]],
                      hand2_data: Tuple[HandRank, List[int]]) -> int:
        """Compare two hands. Returns 1 if hand1 wins, -1 if hand2 wins, 0 if tie"""
        rank1, tb1 = hand1_data
        rank2, tb2 = hand2_data

        # Compare hand ranks first
        if rank1.value > rank2.value:
            return 1
        elif rank1.value < rank2.value:
            return -1

        # Same rank, compare tiebreakers
        return PokerHand._compare_tiebreakers(tb1, tb2)


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


class RaiseModal(discord.ui.Modal):
    """Enhanced modal for custom raise amounts"""

    def __init__(self, view, player_idx: int):
        super().__init__(title="레이즈 금액 선택", timeout=30)
        self.view = view
        self.player_idx = player_idx

        player = view.game.players[player_idx]
        min_raise_total = view.game.current_bet + view.game.big_blind
        max_chips = player.chips

        self.raise_input = discord.ui.TextInput(
            label="레이즈 총 금액",
            placeholder=f"최소: {min_raise_total}칩, 최대: {player.current_bet + max_chips}칩",
            required=True,
            max_length=10
        )
        self.add_item(self.raise_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            total_bet = int(self.raise_input.value)

            # ENHANCED: Validate game state first
            if self.view.game.game_over or self.view.join_phase:
                await interaction.response.send_message("⌚ 게임이 종료되었거나 아직 시작되지 않았습니다!", ephemeral=True)
                return

            if self.player_idx >= len(self.view.game.players):
                await interaction.response.send_message("❌ 플레이어 정보를 찾을 수 없습니다!", ephemeral=True)
                return

            player = self.view.game.players[self.player_idx]

            # Double-check it's still this player's turn
            if self.player_idx != self.view.game.current_player:
                await interaction.response.send_message("⌚ 더 이상 당신의 차례가 아닙니다!", ephemeral=True)
                return

            if not self.view.waiting_for_action:
                await interaction.response.send_message("❌ 이미 액션이 처리되었습니다!", ephemeral=True)
                return

            # Validate raise amount
            min_raise_total = self.view.game.current_bet + self.view.game.big_blind
            max_total = player.current_bet + player.chips

            if total_bet < min_raise_total:
                await interaction.response.send_message(f"❌ 최소 레이즈 금액은 {min_raise_total:,}칩입니다!", ephemeral=True)
                return

            if total_bet > max_total:
                await interaction.response.send_message(f"❌ 보유 칩이 부족합니다! 최대: {max_total:,}칩", ephemeral=True)
                return

            # Make the raise
            success = self.view.game.make_raise(self.player_idx, total_bet)
            if not success:
                await interaction.response.send_message("❌ 레이즈 처리에 실패했습니다!", ephemeral=True)
                return

            # FIXED: Atomic state update
            self.view.waiting_for_action = False
            next_player = self.view.game.get_next_active_player(self.view.game.current_player)
            self.view.game.current_player = next_player

            embed = self.view.create_game_embed()
            await interaction.response.edit_message(embed=embed, view=self.view)

        except ValueError:
            await interaction.response.send_message("❌ 유효한 숫자를 입력해주세요!", ephemeral=True)
        except Exception as e:
            self.view.logger.error(f"Error in raise modal: {e}")
            await interaction.response.send_message("❌ 처리 중 오류가 발생했습니다!", ephemeral=True)


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
        self.logger = get_logger("텍사스홀덤")

    def validate_game_state(self) -> bool:
        """Validate current game state consistency"""
        try:
            # Basic bounds checking
            if self.current_player < -1 or self.current_player >= len(self.players):
                self.logger.warning(f"Invalid current_player: {self.current_player}, players: {len(self.players)}")
                return False

            # If current_player is valid, they should be able to act
            if self.current_player >= 0 and not self.can_act(self.current_player):
                self.logger.warning(f"Current player {self.current_player} cannot act")
                return False

            # Betting round should be valid
            if self.betting_round < 0 or self.betting_round > 3:
                self.logger.warning(f"Invalid betting_round: {self.betting_round}")
                return False

            # Community cards should match betting round
            expected_cards = [0, 3, 4, 5][self.betting_round]
            if len(self.community_cards) != expected_cards:
                self.logger.warning(
                    f"Card count mismatch: round {self.betting_round}, cards {len(self.community_cards)}")
                return False

            # Validate pot consistency
            total_bets = sum(player.total_bet for player in self.players)
            if total_bets != self.pot:
                self.logger.warning(f"Pot inconsistency: calculated {total_bets}, actual {self.pot}")
                return False

            # Validate current bet consistency
            active_players = [p for p in self.players if not p.folded and not p.all_in]
            if active_players:
                max_current_bet = max(p.current_bet for p in active_players)
                if self.current_bet != max_current_bet:
                    self.logger.warning(
                        f"Current bet inconsistency: game {self.current_bet}, max player {max_current_bet}")
                    return False

            return True
        except Exception as e:
            self.logger.error(f"Game state validation error: {e}")
            return False

    def get_action_summary(self, player_idx: int) -> str:
        """Get a summary of available actions for display"""
        if player_idx < 0 or player_idx >= len(self.players):
            return "액션 없음"

        actions = self.get_valid_actions(player_idx)
        if not actions:
            return "액션 없음"

        player = self.players[player_idx]
        to_call = self.current_bet - player.current_bet

        summary_parts = []
        if "fold" in actions:
            summary_parts.append("폴드")
        if "check" in actions:
            summary_parts.append("체크")
        if "call" in actions:
            summary_parts.append(f"콜 ({to_call:,}칩)")
        if "raise" in actions:
            min_raise = self.current_bet + self.big_blind
            summary_parts.append(f"레이즈 (최소 {min_raise:,}칩)")
        if "allin" in actions:
            summary_parts.append(f"올인 ({player.chips:,}칩)")

        return " | ".join(summary_parts) if summary_parts else "액션 없음"

    def recover_from_invalid_state(self):
        """Attempt to recover from an invalid game state"""
        try:
            self.logger.warning("Attempting to recover from invalid game state")

            # Fix current_player if invalid
            if self.current_player < 0 or self.current_player >= len(self.players):
                # Find next active player starting from dealer
                self.current_player = self.get_next_active_player(self.dealer_pos)
                if self.current_player == -1:
                    # No active players, end game
                    self.game_over = True
                    return True

            # If current player can't act, find next one
            if self.current_player >= 0 and not self.can_act(self.current_player):
                next_player = self.get_next_active_player(self.current_player)
                if next_player == -1:
                    # No more active players
                    self.game_over = True
                    return True
                self.current_player = next_player

            # Validate pot consistency and fix if needed
            total_bets = sum(player.total_bet for player in self.players)
            if total_bets != self.pot:
                self.logger.warning(f"Fixing pot: was {self.pot}, should be {total_bets}")
                self.pot = total_bets

            # Recalculate current bet
            active_players = [p for p in self.players if not p.folded]
            if active_players:
                self.current_bet = max(p.current_bet for p in active_players)

            return True
        except Exception as e:
            self.logger.error(f"Recovery failed: {e}")
            return False

    def log_game_state(self, context: str = ""):
        """Log current game state for debugging"""
        try:
            active_count = len([p for p in self.players if not p.folded])
            all_in_count = len([p for p in self.players if p.all_in])

            state_info = {
                'context': context,
                'game_over': self.game_over,
                'betting_round': self.betting_round,
                'current_player': self.current_player,
                'pot': self.pot,
                'current_bet': self.current_bet,
                'total_players': len(self.players),
                'active_players': active_count,
                'all_in_players': all_in_count,
                'community_cards': len(self.community_cards)
            }

            self.logger.debug(f"Game state {context}: {state_info}")

            # Log each player's state
            for i, player in enumerate(self.players):
                player_info = {
                    'index': i,
                    'username': player.username,
                    'chips': player.chips,
                    'current_bet': player.current_bet,
                    'total_bet': player.total_bet,
                    'folded': player.folded,
                    'all_in': player.all_in,
                    'acted': player.acted_this_round
                }
                self.logger.debug(f"Player {i}: {player_info}")

        except Exception as e:
            self.logger.error(f"Error logging game state: {e}")

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

        self.log_game_state("after_hand_start")
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
        elif action == "allin":
            amount = player.chips
            player.chips = 0
            player.current_bet += amount
            player.total_bet += amount
            self.pot += amount
            self.current_bet = max(self.current_bet, player.current_bet)
            player.all_in = True

        player.acted_this_round = True
        self.log_game_state(f"after_{action}_by_player_{player_idx}")
        return True

    def make_raise(self, player_idx: int, total_bet_amount: int) -> bool:
        """Process raise action with specific total bet amount"""
        if not self.can_act(player_idx):
            return False

        player = self.players[player_idx]

        # Calculate how much more the player needs to bet
        additional_bet = total_bet_amount - player.current_bet

        if additional_bet > player.chips:
            return False

        # Minimum raise check
        min_raise_total = self.current_bet + self.big_blind
        if total_bet_amount < min_raise_total:
            return False

        # Make the raise
        player.chips -= additional_bet
        player.current_bet = total_bet_amount
        player.total_bet += additional_bet
        self.pot += additional_bet
        self.current_bet = total_bet_amount

        if player.chips == 0:
            player.all_in = True

        player.acted_this_round = True

        # Reset other players' action status for this round since bet increased
        for other_player in self.players:
            if other_player != player and not other_player.folded and not other_player.all_in:
                other_player.acted_this_round = False

        self.log_game_state(f"after_raise_to_{total_bet_amount}_by_player_{player_idx}")
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
        self.log_game_state(f"advanced_to_round_{self.betting_round}")

    def get_next_active_player(self, start_pos: int) -> int:
        """Get next player who can act, with better error handling"""
        if not self.players:
            return -1

        # Ensure start_pos is valid
        start_pos = max(0, min(start_pos, len(self.players) - 1))

        for i in range(1, len(self.players) + 1):
            pos = (start_pos + i) % len(self.players)
            if pos < len(self.players) and self.can_act(pos):
                return pos

        # No active players found
        self.logger.warning("No active players found")
        return -1

    def determine_winners(self):
        """Fixed winner determination with proper hand comparison"""
        active_players = [p for p in self.players if not p.folded]

        if len(active_players) == 1:
            # Only one player left
            winner = active_players[0]
            winner.chips += self.pot
            self.winners = [winner]
            self.log_game_state("winner_by_elimination")
            return

        # Evaluate hands for all active players
        player_hands = []
        for player in active_players:
            try:
                all_cards = player.hole_cards + self.community_cards
                if len(all_cards) != 7:
                    self.logger.error(f"Player {player.username} has {len(all_cards)} cards instead of 7")
                    continue

                hand_rank, tiebreakers = PokerHand.evaluate_hand(all_cards)
                player_hands.append((player, hand_rank, tiebreakers))

                # Debug logging
                self.logger.debug(f"Player {player.username}: {hand_rank.name} with tiebreakers {tiebreakers}")

            except Exception as e:
                self.logger.error(f"Error evaluating hand for {player.username}: {e}")
                # Give them high card with lowest possible tiebreakers
                player_hands.append((player, HandRank.HIGH_CARD, [2, 3, 4, 5, 7]))

        if not player_hands:
            self.logger.error("No valid hands to evaluate!")
            return

        # Find the best hand(s)
        best_players = [player_hands[0]]  # Start with first player

        for i in range(1, len(player_hands)):
            current_player_data = player_hands[i]
            current_hand = (current_player_data[1], current_player_data[2])
            best_hand = (best_players[0][1], best_players[0][2])

            comparison = PokerHand.compare_hands(current_hand, best_hand)

            if comparison > 0:  # Current hand is better
                best_players = [current_player_data]
            elif comparison == 0:  # Tie
                best_players.append(current_player_data)

        # Extract just the players from the best hands
        winners = [player_data[0] for player_data in best_players]

        # Distribute pot equally among winners
        pot_share = self.pot // len(winners)
        remainder = self.pot % len(winners)

        for i, winner in enumerate(winners):
            share = pot_share + (1 if i < remainder else 0)
            winner.chips += share

        self.winners = winners

        # Debug logging
        winner_names = [w.username for w in winners]
        self.logger.info(f"Winners: {winner_names}, pot: {self.pot}, shares: {pot_share}")


class HoldemView(discord.ui.View):
    """Interactive Texas Hold'em game view with standardized embeds"""

    def __init__(self, bot, guild_id: int, channel_id: int, buy_in: int, creator_id: int, creator_name: str):
        super().__init__(timeout=300)  # 5 minutes
        self.bot = bot
        self.game = HoldemGame(bot, guild_id, channel_id, buy_in)
        self.join_phase = True
        self.waiting_for_action = False
        self.current_message = None
        self.logger = get_logger("텍사스홀덤")

        # Add creator as first player
        self.game.add_player(creator_id, creator_name)

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

    def create_poker_display(self) -> str:
        """Create standardized poker display"""
        round_names = ["프리플랍", "플랍", "턴", "리버"]
        round_name = round_names[min(self.game.betting_round, 3)]

        current_player = None
        if 0 <= self.game.current_player < len(self.game.players):
            current_player = self.game.players[self.game.current_player]

        display = f"🎲 **라운드:** {round_name}\n"
        display += f"💰 **팟:** {self.game.pot:,}칩\n"
        display += f"📊 **현재 베팅:** {self.game.current_bet}칩"

        if current_player and not self.game.game_over:
            display += f"\n\n🎯 **현재 차례:** {current_player.username}"
            action_summary = self.game.get_action_summary(self.game.current_player)
            if action_summary != "액션 없음":
                display += f"\n🎮 **가능한 액션:** {action_summary}"

        return display

    async def handle_player_turn(self):
        """Enhanced player turn handling with atomic state updates and validation"""
        while not self.game.game_over and not self.join_phase:
            # ENHANCED: Validate game state before each turn
            if not self.game.validate_game_state():
                self.logger.error("Invalid game state detected, attempting recovery")
                self.game.log_game_state("before_recovery")

                if not self.game.recover_from_invalid_state():
                    self.logger.error("Could not recover from invalid state, ending game")
                    self.game.game_over = True
                    await self.show_results()
                    return

                self.game.log_game_state("after_recovery")

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
                    try:
                        if self.current_message:
                            embed = self.create_game_embed()
                            await self.current_message.edit(embed=embed, view=self)
                    except Exception as e:
                        self.logger.error(f"Error updating embed after round advance: {e}")

            # Check if only one player left
            active_players = [p for p in self.game.players if not p.folded]
            if len(active_players) <= 1:
                if active_players:
                    self.game.winners = active_players
                    active_players[0].chips += self.game.pot
                self.game.game_over = True
                await self.show_results()
                return

            # ENHANCED: Better validation of current player
            if (self.game.current_player == -1 or
                    self.game.current_player >= len(self.game.players) or
                    not self.game.can_act(self.game.current_player)):

                # Try to find next valid player
                next_player = self.game.get_next_active_player(self.game.current_player)
                if next_player == -1:
                    # No valid players, end game
                    self.game.game_over = True
                    await self.show_results()
                    return
                self.game.current_player = next_player

            # ENHANCED: Atomic state update before waiting
            self.waiting_for_action = True

            try:
                if self.current_message:
                    embed = self.create_game_embed()
                    await self.current_message.edit(embed=embed, view=self)
            except Exception as e:
                self.logger.error(f"Error updating embed before player turn: {e}")

            # Wait for action with timeout
            for _ in range(30):  # 30 second timer
                if not self.waiting_for_action or self.game.game_over:
                    break
                await asyncio.sleep(1)

            # Auto-fold if no action taken and game still active
            if self.waiting_for_action and not self.game.game_over:
                self.logger.info(
                    f"Player {self.game.players[self.game.current_player].username} auto-folded due to timeout")
                self.game.make_action(self.game.current_player, "fold")
                self.waiting_for_action = False
                self.game.current_player = self.game.get_next_active_player(self.game.current_player)

    async def show_results(self):
        """Fixed results display with proper cleanup"""
        self.clear_items()

        # Calculate results for each player
        player_results = []
        for player in self.game.players:
            net_result = player.chips - self.game.buy_in  # chips now - original buy-in
            player_results.append({
                'player': player,
                'final_chips': player.chips,
                'net': net_result,
                'is_winner': player in self.game.winners if self.game.winners else False
            })

        # Handle payouts
        coins_cog = self.bot.get_cog('CoinsCog')
        if coins_cog:
            for result in player_results:
                if result['final_chips'] > 0:
                    # Return remaining chips as coins
                    await coins_cog.add_coins(
                        result['player'].user_id,
                        self.game.guild_id,
                        result['final_chips'],
                        "holdem_payout",
                        f"텍사스 홀덤 정산 ({result['final_chips']}칩)"
                    )

        # Create results embed
        embed = discord.Embed(
            title="🎉 텍사스 홀덤 결과",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow()
        )

        # Winner announcement
        if self.game.winners:
            if len(self.game.winners) == 1:
                winner = self.game.winners[0]
                embed.add_field(
                    name="🏆 승리자",
                    value=f"**{winner.username}**",
                    inline=False
                )
            else:
                winner_names = [w.username for w in self.game.winners]
                embed.add_field(
                    name="🏆 승리자들 (동점)",
                    value=", ".join(f"**{name}**" for name in winner_names),
                    inline=False
                )

        # Show final community cards
        if self.game.community_cards:
            cards_str = " ".join(str(card) for card in self.game.community_cards)
            embed.add_field(name="🃏 최종 커뮤니티 카드", value=cards_str, inline=False)

        # Player results breakdown
        results_text = []
        for result in player_results:
            player = result['player']
            status = "🏆" if result['is_winner'] else "💸" if result['net'] < 0 else "💰" if result['net'] > 0 else "➖"

            # Net result display
            if result['net'] > 0:
                net_display = f"+{result['net']:,}코인"
            elif result['net'] < 0:
                net_display = f"{result['net']:,}코인"
            else:
                net_display = "±0코인"

            results_text.append(
                f"{status} **{player.username}**\n"
                f"   최종: {result['final_chips']:,}칩 ({net_display})"
            )

        embed.add_field(
            name="💳 플레이어 정산",
            value="\n\n".join(results_text),
            inline=False
        )

        # Game summary
        total_pot = sum(p.total_bet for p in self.game.players)
        embed.add_field(
            name="🎯 게임 요약",
            value=f"💰 총 팟: {total_pot:,}칩\n💳 바이인: {self.game.buy_in:,}코인\n👥 참가자: {len(self.game.players)}명",
            inline=False
        )

        # Show winning hand if available
        if self.game.winners and self.game.community_cards:
            try:
                winner = self.game.winners[0]
                all_cards = winner.hole_cards + self.game.community_cards
                hand_rank, _ = PokerHand.evaluate_hand(all_cards)

                hand_names = {
                    HandRank.HIGH_CARD: "하이카드",
                    HandRank.PAIR: "원페어",
                    HandRank.TWO_PAIR: "투페어",
                    HandRank.THREE_KIND: "쓰리오브어카인드",
                    HandRank.STRAIGHT: "스트레이트",
                    HandRank.FLUSH: "플러시",
                    HandRank.FULL_HOUSE: "풀하우스",
                    HandRank.FOUR_KIND: "포오브어카인드",
                    HandRank.STRAIGHT_FLUSH: "스트레이트 플러시",
                    HandRank.ROYAL_FLUSH: "로얄 플러시"
                }

                embed.add_field(
                    name="🎯 승리 패",
                    value=f"**{hand_names.get(hand_rank, '알 수 없음')}**",
                    inline=False
                )
            except:
                pass  # If hand evaluation fails, just skip this

        embed.set_footer(text=f"Server: {self.bot.get_guild(self.game.guild_id).name}")

        if self.current_message:
            try:
                await self.current_message.edit(embed=embed, view=self)
            except:
                pass

        # FIXED: Clean up the game from active games (proper indentation)
        if hasattr(self.bot, 'get_cog'):
            holdem_cog = self.bot.get_cog('HoldemCog')
            if holdem_cog and self.game.channel_id in holdem_cog.active_games:
                del holdem_cog.active_games[self.game.channel_id]

    def create_game_embed(self) -> discord.Embed:
        """Create game status embed with standardized format"""
        if self.join_phase:
            title = "🃏 텍사스 홀덤"
            color = discord.Color.blue()
        elif self.game.game_over:
            title = "🃏 텍사스 홀덤 - 🎉 게임 완료!"
            color = discord.Color.gold()
        else:
            title = "🃏 텍사스 홀덤 - 진행 중"
            color = discord.Color.green()

        embed = discord.Embed(title=title, color=color, timestamp=discord.utils.utcnow())

        if self.join_phase:
            # STANDARDIZED FIELD 1: Game Display (during join phase)
            embed.add_field(
                name="🎯 게임 상태",
                value=f"🔥 **플레이어 모집 중**\n\n👥 **참가자:** {len(self.game.players)}/8명\n💰 **바이인:** {self.game.buy_in:,}코인",
                inline=False
            )

            # STANDARDIZED FIELD 2: Betting Info
            embed.add_field(
                name="💳 베팅 정보",
                value=f"💰 **바이인:** {self.game.buy_in:,}코인\n🎲 **상태:** 플레이어 모집 중\n🔸 **스몰블라인드:** {self.game.small_blind}칩\n🔹 **빅블라인드:** {self.game.big_blind}칩",
                inline=False
            )

            if self.game.players:
                player_list = []
                for player in self.game.players:
                    player_list.append(f"🎰 {player.username}")
                embed.add_field(name="👥 참가자", value="\n".join(player_list), inline=False)

            embed.add_field(
                name="📋 게임 규칙",
                value="• 바이인으로 칩을 받아 게임 시작\n• 최고 핸드가 팟을 가져감\n• 칩이 떨어지면 탈락\n• 홀카드는 개인 메시지로 전송됩니다\n• 30초 내 액션하지 않으면 자동 폴드",
                inline=False
            )

        else:
            # STANDARDIZED FIELD 1: Game Display
            embed.add_field(
                name="🎯 홀덤 현황",
                value=self.create_poker_display(),
                inline=False
            )

            # STANDARDIZED FIELD 2: Betting Info
            embed.add_field(
                name="💳 베팅 정보",
                value=f"💰 **바이인:** {self.game.buy_in:,}코인\n🎲 **상태:** 게임 진행 중",
                inline=False
            )

            # Community cards
            if self.game.community_cards:
                cards_str = " ".join(str(card) for card in self.game.community_cards)
                embed.add_field(name="🃏 커뮤니티 카드", value=cards_str, inline=False)

            # Player info
            player_info = []
            for i, player in enumerate(self.game.players):
                status = ""
                if player.folded:
                    status = " (폴드)"
                elif player.all_in:
                    status = " (올인)"
                elif i == self.game.current_player:
                    status = " 👈"

                player_info.append(f"**{player.username}:** {player.chips}칩 (베팅:{player.current_bet}){status}")

            embed.add_field(name="👥 플레이어 현황", value="\n".join(player_info), inline=False)

            # Note about hole cards
            embed.add_field(
                name="🔒 참고",
                value="홀카드는 개인 메시지로 확인하세요!",
                inline=False
            )

        # Standardized footer
        embed.set_footer(text=f"Server: {self.bot.get_guild(self.game.guild_id).name}")
        return embed

    @discord.ui.button(label="🎰 게임 참가", style=discord.ButtonStyle.green)
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.join_phase:
            await interaction.response.send_message("❌ 게임이 이미 시작되었습니다!", ephemeral=True)
            return

        # Check if already joined
        if any(p.user_id == interaction.user.id for p in self.game.players):
            await interaction.response.send_message("❌ 이미 게임에 참가하셨습니다!", ephemeral=True)
            return

        # =================================================================
        # LOAN RESTRICTION CHECK FOR JOINING PLAYERS
        # =================================================================
        restriction = await check_user_casino_eligibility(self.bot, interaction.user.id, interaction.guild.id)
        if not restriction['allowed']:
            await interaction.response.send_message(restriction['message'], ephemeral=True)
            return
        # =================================================================

        # FIXED: Proper booster limit validation for joining players
        casino_base = self.bot.get_cog('CasinoBaseCog')
        if casino_base:
            # Get the user's betting limit (considers booster status)
            booster_cog = self.bot.get_cog('BoosterPerks')
            if booster_cog:
                user_max_bet = booster_cog.get_betting_limit(interaction.user)
            else:
                user_max_bet = 1000  # Default max for hold'em

            # Check if user can afford the buy-in within their limits
            if self.game.buy_in > user_max_bet:
                await interaction.response.send_message(
                    f"❌ 이 게임의 바이인({self.game.buy_in:,}코인)이 당신의 베팅 한도({user_max_bet:,}코인)를 초과합니다!\n"
                    f"{'서버 부스터가 되면 베팅 한도가 증가합니다!' if user_max_bet < 1000 else ''}",
                    ephemeral=True
                )
                return

            # Standard casino validation (balance check, etc.)
            can_start, error_msg = await casino_base.validate_game_start(
                interaction, "holdem", self.game.buy_in, 100, user_max_bet  # Use user's actual limit
            )
            if not can_start:
                await interaction.response.send_message(error_msg, ephemeral=True)
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

    @discord.ui.button(label="❌ 나가기", style=discord.ButtonStyle.red)
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.join_phase:
            await interaction.response.send_message("❌ 게임이 시작된 후에는 나갈 수 없습니다!", ephemeral=True)
            return

        if not any(p.user_id == interaction.user.id for p in self.game.players):
            await interaction.response.send_message("❌ 참가하지 않으셨습니다!", ephemeral=True)
            return

        await interaction.response.defer()

        # Find and refund player
        player_to_remove = None
        for player in self.game.players:
            if player.user_id == interaction.user.id:
                player_to_remove = player
                break

        if player_to_remove:
            # Refund buy-in
            coins_cog = self.bot.get_cog('CoinsCog')
            if coins_cog:
                await coins_cog.add_coins(
                    interaction.user.id,
                    interaction.guild.id,
                    self.game.buy_in,
                    "holdem_refund",
                    "텍사스 홀덤 나가기 환불"
                )

            # Remove player
            self.game.remove_player(interaction.user.id)

        # Check if no players left - close game
        if not self.game.players:
            self.clear_items()
            embed = discord.Embed(
                title="🃏 텍사스 홀덤 종료",
                description="모든 플레이어가 나가서 게임이 종료되었습니다.",
                color=discord.Color.red()
            )
            if self.current_message:
                await self.current_message.edit(embed=embed, view=self)
            return

        embed = self.create_game_embed()
        if self.current_message:
            await self.current_message.edit(embed=embed, view=self)

    @discord.ui.button(label="🚀 게임 시작", style=discord.ButtonStyle.primary)
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.start_game(interaction)

    async def on_timeout(self):
        """Clean up when view times out"""
        # Clean up the game from active games
        if hasattr(self.bot, 'get_cog'):
            holdem_cog = self.bot.get_cog('HoldemCog')
            if holdem_cog and self.game.channel_id in holdem_cog.active_games:
                del holdem_cog.active_games[self.game.channel_id]

        # Disable all buttons
        self.clear_items()

        # Try to update message to show timeout
        if self.current_message:
            try:
                embed = discord.Embed(
                    title="⏰ 게임 시간 초과",
                    description="게임이 비활성으로 인해 종료되었습니다.",
                    color=discord.Color.red()
                )
                await self.current_message.edit(embed=embed, view=self)
            except:
                pass


class ActionButton(discord.ui.Button):
    """Enhanced poker action button with better validation"""

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

        # Check if game is over
        if game.game_over or view.join_phase:
            await interaction.response.send_message("❌ 게임이 종료되었거나 아직 시작되지 않았습니다!", ephemeral=True)
            return

        # ENHANCED: Check current player with better error messages
        if player_idx != game.current_player:
            if 0 <= game.current_player < len(game.players):
                current_player_name = game.players[game.current_player].username
                await interaction.response.send_message(f"❌ 지금은 **{current_player_name}**님의 차례입니다!", ephemeral=True)
            else:
                await interaction.response.send_message("❌ 현재 액션할 수 있는 플레이어가 없습니다!", ephemeral=True)
            return

        # Check if we're still waiting for this player's action
        if not view.waiting_for_action:
            await interaction.response.send_message("❌ 이미 액션이 처리되었습니다!", ephemeral=True)
            return

        # ENHANCED: Better action validation with specific error messages
        valid_actions = game.get_valid_actions(player_idx)
        if self.action not in valid_actions:
            error_messages = {
                "fold": "❌ 폴드할 수 없습니다!",
                "check": "❌ 체크할 수 없습니다! (베팅이 있습니다)",
                "call": "❌ 콜할 수 없습니다! (베팅 금액이 부족하거나 베팅이 없습니다)",
                "raise": "❌ 레이즈할 수 없습니다! (칩이 부족합니다)",
                "allin": "❌ 올인할 수 없습니다!"
            }
            await interaction.response.send_message(error_messages.get(self.action, "❌ 유효하지 않은 액션입니다!"), ephemeral=True)
            return

        # Handle raise action with modal
        if self.action == "raise":
            modal = RaiseModal(view, player_idx)
            await interaction.response.send_modal(modal)
            return

        # Handle other actions
        success = game.make_action(player_idx, self.action)
        if not success:
            await interaction.response.send_message("❌ 액션 처리에 실패했습니다!", ephemeral=True)
            return

        # FIXED: Update state atomically
        view.waiting_for_action = False
        next_player = game.get_next_active_player(game.current_player)
        game.current_player = next_player

        embed = view.create_game_embed()
        await interaction.response.edit_message(embed=embed, view=view)


class HoldemCog(commands.Cog):
    """Texas Hold'em Poker game with standardized embeds"""

    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("텍사스홀덤")
        self.active_games: Dict[int, HoldemView] = {}  # channel_id -> game
        self.logger.info("텍사스 홀덤 게임 시스템이 초기화되었습니다.")

    @app_commands.command(name="홀덤", description="텍사스 홀덤 포커 게임을 시작합니다")
    @app_commands.describe(buy_in="바이인 금액 (100-1000코인)")
    async def holdem(self, interaction: discord.Interaction, buy_in: int = 100):
        try:
            # Check if casino games are enabled for this server
            if not interaction.guild or not is_feature_enabled(interaction.guild.id, 'casino_games'):
                await interaction.response.send_message("❌ 이 서버에서는 카지노 게임이 비활성화되어 있습니다!", ephemeral=True)
                return

            restriction = await check_user_casino_eligibility(self.bot, interaction.user.id, interaction.guild.id)
            if not restriction['allowed']:
                await interaction.response.send_message(restriction['message'], ephemeral=True)
                return

            # FIXED: Apply booster limits to buy-in validation
            casino_base = self.bot.get_cog('CasinoBaseCog')
            if casino_base:
                # Get the user's betting limit (considers booster status)
                booster_cog = self.bot.get_cog('BoosterPerks')
                if booster_cog:
                    user_max_bet = booster_cog.get_betting_limit(interaction.user)
                else:
                    user_max_bet = 1000  # Default max for hold'em

                # Validate with user's actual limits
                can_start, error_msg = await casino_base.validate_game_start(
                    interaction, "holdem", buy_in, 100, user_max_bet  # Use user's actual limit
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

            # Deduct creator's buy-in
            coins_cog = self.bot.get_cog('CoinsCog')
            success = await coins_cog.remove_coins(
                interaction.user.id,
                interaction.guild.id,
                buy_in,
                "holdem_buyin",
                f"텍사스 홀덤 바이인 ({buy_in}코인)"
            )

            if not success:
                await interaction.response.send_message("❌ 바이인 처리에 실패했습니다!", ephemeral=True)
                return

            # Create new game with creator already included
            game_view = HoldemView(
                self.bot,
                interaction.guild.id,
                channel_id,
                buy_in,
                interaction.user.id,
                interaction.user.display_name
            )
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