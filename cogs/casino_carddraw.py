# cogs/casino_carddraw.py - Card Draw Battle game (FIXED)
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


class CardSuit(Enum):
    HEARTS = "♥️"
    DIAMONDS = "♦️"
    CLUBS = "♣️"
    SPADES = "♠️"


class DrawCard:
    """Represents a playing card for draw battle"""

    def __init__(self, rank: int, suit: CardSuit):
        self.rank = rank  # 2-14 (11=J, 12=Q, 13=K, 14=A)
        self.suit = suit
        self.value = rank  # For comparison (Ace high)

    def __str__(self):
        rank_names = {11: "J", 12: "Q", 13: "K", 14: "A"}
        rank_str = rank_names.get(self.rank, str(self.rank))
        return f"{rank_str}{self.suit.value}"

    def __eq__(self, other):
        return self.value == other.value

    def __lt__(self, other):
        return self.value < other.value

    def __gt__(self, other):
        return self.value > other.value


class CardDrawDeck:
    """Deck for card draw battles"""

    def __init__(self):
        self.cards = []
        self.reset()

    def reset(self):
        """Reset and shuffle deck"""
        self.cards = []
        for suit in CardSuit:
            for rank in range(2, 15):  # 2-14 (A)
                self.cards.append(DrawCard(rank, suit))
        random.shuffle(self.cards)

    def draw_card(self) -> DrawCard:
        """Draw one card"""
        if not self.cards:
            self.reset()
        return self.cards.pop()


class CardDrawPlayer:
    """Player in card draw battle"""

    def __init__(self, user_id: int, username: str, bet: int):
        self.user_id = user_id
        self.username = username
        self.bet = bet
        self.card = None
        self.ready = False


class CardDrawView(discord.ui.View):
    """Interactive Card Draw Battle view"""

    def __init__(self, bot, guild_id: int, channel_id: int, creator_id: int, bet: int):
        super().__init__(timeout=180)  # 3 minutes
        self.bot = bot
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.bet = bet
        self.players: Dict[int, CardDrawPlayer] = {}
        self.deck = CardDrawDeck()
        self.join_phase = True
        self.battle_phase = False
        self.game_over = False
        self.winner = None
        self.is_tie = False
        self.message = None

        # Add creator as first player
        self.add_player(creator_id, "플레이어", bet)

    def add_player(self, user_id: int, username: str, bet: int) -> bool:
        """Add player to the battle"""
        if user_id not in self.players and len(self.players) < 6:  # Max 6 players
            self.players[user_id] = CardDrawPlayer(user_id, username, bet)
            return True
        return False

    def remove_player(self, user_id: int) -> bool:
        """Remove player from battle"""
        if user_id in self.players and self.join_phase:
            del self.players[user_id]
            return True
        return False

    async def start_battle(self, interaction: discord.Interaction):
        """Start the card drawing battle"""
        if len(self.players) < 2:
            await interaction.response.send_message("❌ 최소 2명의 플레이어가 필요합니다!", ephemeral=True)
            return

        self.join_phase = False
        self.battle_phase = True

        # Clear join/leave buttons and add draw button
        self.clear_items()
        self.add_item(DrawCardButton())

        embed = self.create_battle_embed()
        await interaction.response.edit_message(embed=embed, view=self)

        # Wait for all players to draw
        await self.wait_for_all_draws()

    async def start_battle_direct(self):
        """Start battle without interaction (for auto-start)"""
        if len(self.players) < 2:
            return

        self.join_phase = False
        self.battle_phase = True
        self.clear_items()
        self.add_item(DrawCardButton())

        embed = self.create_battle_embed()
        if self.message:
            await self.message.edit(embed=embed, view=self)

        await self.wait_for_all_draws()

    async def wait_for_all_draws(self):
        """Wait for all players to draw their cards"""
        timeout_counter = 0
        max_timeout = 60  # 60 seconds timeout

        while self.battle_phase and not self.game_over and timeout_counter < max_timeout:
            all_ready = True
            for player in self.players.values():
                if not player.ready:
                    all_ready = False
                    break

            if all_ready:
                await self.resolve_battle()
                break

            await asyncio.sleep(1)
            timeout_counter += 1

        # Auto-resolve after timeout
        if self.battle_phase and not self.game_over:
            await self.resolve_battle()

    async def draw_card_for_player(self, interaction: discord.Interaction, user_id: int):
        """Handle player drawing a card"""
        await interaction.response.defer(ephemeral=True)

        if user_id not in self.players:
            await interaction.followup.send("❌ 이 배틀에 참가하지 않으셨습니다!", ephemeral=True)
            return

        player = self.players[user_id]
        if player.ready:
            await interaction.followup.send("❌ 이미 카드를 뽑으셨습니다!", ephemeral=True)
            return

        # Draw card
        player.card = self.deck.draw_card()
        player.ready = True

        # Show card to player privately
        embed = discord.Embed(
            title="🃏 당신의 카드",
            description=f"**뽑은 카드:** {player.card}\n\n다른 플레이어들이 카드를 뽑을 때까지 기다려주세요!",
            color=discord.Color.blue()
        )

        await interaction.followup.send(embed=embed, ephemeral=True)

        # Update main message
        if self.message:
            embed = self.create_battle_embed()
            await self.message.edit(embed=embed, view=self)

    async def resolve_battle(self):
        """Resolve the card draw battle"""
        self.battle_phase = False
        self.game_over = True

        # Auto-draw for players who didn't draw
        for player in self.players.values():
            if not player.ready:
                player.card = self.deck.draw_card()
                player.ready = True

        # Find highest card(s)
        highest_value = max(player.card.value for player in self.players.values())
        winners = [player for player in self.players.values() if player.card.value == highest_value]

        if len(winners) == 1:
            self.winner = winners[0]
        else:
            self.is_tie = True
            self.winner = winners  # Multiple winners

        # Disable buttons
        self.clear_items()

        # Handle payouts
        await self.handle_payouts()

        # Update display
        embed = self.create_results_embed()
        if self.message:
            await self.message.edit(embed=embed, view=self)

    async def handle_payouts(self):
        """Handle coin payouts"""
        coins_cog = self.bot.get_cog('CoinsCog')
        if not coins_cog:
            return

        total_pot = sum(player.bet for player in self.players.values())

        if not self.is_tie and self.winner:
            # Single winner takes all
            await coins_cog.add_coins(
                self.winner.user_id,
                self.guild_id,
                total_pot,
                "carddraw_win",
                f"카드 뽑기 대결 승리 - {self.winner.card}"
            )
        elif self.is_tie and isinstance(self.winner, list):
            # Split pot among winners
            winners = self.winner
            pot_share = total_pot // len(winners)
            remainder = total_pot % len(winners)

            for i, winner in enumerate(winners):
                share = pot_share + (1 if i < remainder else 0)
                await coins_cog.add_coins(
                    winner.user_id,
                    self.guild_id,
                    share,
                    "carddraw_tie",
                    f"카드 뽑기 대결 무승부 분할 - {winner.card}"
                )

    def create_battle_embed(self) -> discord.Embed:
        """Create battle status embed"""
        if self.join_phase:
            title = "🃏 카드 뽑기 대결 - 플레이어 모집"
            color = discord.Color.blue()
            description = f"**베팅금:** {self.bet:,}코인\n**플레이어:** {len(self.players)}/6\n\n'참가하기' 버튼을 눌러 참여하세요!"

            embed = discord.Embed(title=title, description=description, color=color)

            if self.players:
                player_names = []
                for player in self.players.values():
                    player_names.append(f"🎲 {player.username}")
                embed.add_field(name="👥 참가자", value="\n".join(player_names), inline=False)

            embed.add_field(
                name="📋 게임 규칙",
                value="• 모든 플레이어가 한 장씩 카드를 뽑습니다\n• 가장 높은 카드를 뽑은 플레이어가 승리\n• A(에이스)가 가장 높은 카드\n• 동점시 상금을 나눠 가짐\n• 승자가 모든 베팅금을 가져감",
                inline=False
            )

        elif self.battle_phase:
            title = "🃏 카드 뽑기 대결 - 카드 뽑는 중"
            color = discord.Color.orange()

            ready_count = sum(1 for p in self.players.values() if p.ready)
            total_count = len(self.players)

            description = f"**진행 상황:** {ready_count}/{total_count} 플레이어가 카드를 뽑았습니다\n\n아래 버튼을 눌러 카드를 뽑으세요!"

            embed = discord.Embed(title=title, description=description, color=color)

            # Show who's ready
            status_list = []
            for player in self.players.values():
                status = "✅ 완료" if player.ready else "⏳ 대기 중"
                status_list.append(f"{player.username}: {status}")

            embed.add_field(name="👥 플레이어 상태", value="\n".join(status_list), inline=False)

        return embed

    def create_results_embed(self) -> discord.Embed:
        """Create results embed"""
        if not self.is_tie and self.winner:
            title = f"🏆 {self.winner.username} 승리!"
            color = discord.Color.gold()
            total_pot = sum(player.bet for player in self.players.values())
            description = f"**승리 카드:** {self.winner.card}\n**획득 상금:** {total_pot:,}코인"
        elif self.is_tie and isinstance(self.winner, list):
            winners = self.winner
            winner_names = [w.username for w in winners]
            title = f"🤝 무승부! ({len(winners)}명)"
            color = discord.Color.yellow()
            description = f"**동점자:** {', '.join(winner_names)}\n**상금을 분할합니다**"
        else:
            title = "❓ 결과 오류"
            color = discord.Color.red()
            description = "결과 처리 중 오류가 발생했습니다."

        embed = discord.Embed(title=title, description=description, color=color)

        # Show all cards
        card_results = []
        sorted_players = sorted(self.players.values(), key=lambda p: p.card.value, reverse=True)

        for i, player in enumerate(sorted_players):
            rank_emoji = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else "🎴"
            card_results.append(f"{rank_emoji} {player.username}: {player.card}")

        embed.add_field(name="🃏 모든 카드 결과", value="\n".join(card_results), inline=False)

        return embed

    @discord.ui.button(label="🎲 참가하기", style=discord.ButtonStyle.green)
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        if not self.join_phase:
            await interaction.followup.send("❌ 이미 게임이 시작되었습니다!", ephemeral=True)
            return

        if interaction.user.id in self.players:
            await interaction.followup.send("❌ 이미 참가하셨습니다!", ephemeral=True)
            return

        if len(self.players) >= 6:
            await interaction.followup.send("❌ 게임이 가득 찼습니다! (최대 6명)", ephemeral=True)
            return

        # Validate bet
        casino_base = self.bot.get_cog('CasinoBaseCog')
        if casino_base:
            can_start, error_msg = await casino_base.validate_game_start(
                interaction, "carddraw", self.bet, self.bet, self.bet
            )
            if not can_start:
                await interaction.followup.send(error_msg, ephemeral=True)
                return

        # Deduct bet
        coins_cog = self.bot.get_cog('CoinsCog')
        success = await coins_cog.remove_coins(
            interaction.user.id,
            interaction.guild.id,
            self.bet,
            "carddraw_bet",
            f"카드 뽑기 대결 베팅 ({self.bet}코인)"
        )

        if not success:
            await interaction.followup.send("❌ 베팅 처리에 실패했습니다!", ephemeral=True)
            return

        # Add player
        self.add_player(interaction.user.id, interaction.user.display_name, self.bet)

        embed = self.create_battle_embed()
        if self.message:
            await self.message.edit(embed=embed, view=self)

    @discord.ui.button(label="❌ 나가기", style=discord.ButtonStyle.red)
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.join_phase:
            await interaction.response.send_message("❌ 게임이 시작된 후에는 나갈 수 없습니다!", ephemeral=True)
            return

        if interaction.user.id not in self.players:
            await interaction.response.send_message("❌ 참가하지 않으셨습니다!", ephemeral=True)
            return

        await interaction.response.defer()

        # Refund bet
        player = self.players[interaction.user.id]
        coins_cog = self.bot.get_cog('CoinsCog')
        if coins_cog:
            await coins_cog.add_coins(
                interaction.user.id,
                interaction.guild.id,
                player.bet,
                "carddraw_refund",
                "카드 뽑기 대결 나가기 환불"
            )

        # Remove player
        self.remove_player(interaction.user.id)

        # Disable if no players
        if not self.players:
            self.clear_items()

        embed = self.create_battle_embed()
        if self.message:
            await self.message.edit(embed=embed, view=self)

    @discord.ui.button(label="🚀 게임 시작", style=discord.ButtonStyle.primary)
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.start_battle(interaction)

    async def on_timeout(self):
        """Handle timeout"""
        if self.join_phase:
            # Refund all players
            coins_cog = self.bot.get_cog('CoinsCog')
            if coins_cog:
                for player in self.players.values():
                    await coins_cog.add_coins(
                        player.user_id,
                        self.guild_id,
                        player.bet,
                        "carddraw_timeout",
                        "카드 뽑기 대결 시간 초과 환불"
                    )
        elif self.battle_phase:
            await self.resolve_battle()


class DrawCardButton(discord.ui.Button):
    """Button for drawing a card"""

    def __init__(self):
        super().__init__(
            label="🃏 카드 뽑기",
            style=discord.ButtonStyle.primary,
            emoji="🎲"
        )

    async def callback(self, interaction: discord.Interaction):
        await self.view.draw_card_for_player(interaction, interaction.user.id)


class CardDrawCog(commands.Cog):
    """Card Draw Battle game"""

    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("카드뽑기대결")
        self.active_games: Dict[int, CardDrawView] = {}  # channel_id -> game
        self.logger.info("카드 뽑기 대결 게임 시스템이 초기화되었습니다.")

    @app_commands.command(name="카드뽑기", description="카드 뽑기 대결 게임을 시작합니다")
    @app_commands.describe(bet="베팅 금액 (20-500코인)")
    async def carddraw(self, interaction: discord.Interaction, bet: int = 50):
        await interaction.response.defer()

        # Validate game using casino base
        casino_base = self.bot.get_cog('CasinoBaseCog')
        if casino_base:
            can_start, error_msg = await casino_base.validate_game_start(
                interaction, "carddraw", bet, 20, 500
            )
            if not can_start:
                await interaction.followup.send(error_msg, ephemeral=True)
                return

        channel_id = interaction.channel.id

        # Check for existing game
        if channel_id in self.active_games:
            existing = self.active_games[channel_id]
            if existing.join_phase:
                await interaction.followup.send("❌ 이 채널에서 이미 카드 뽑기 대결이 모집 중입니다!", ephemeral=True)
                return
            elif not existing.game_over:
                await interaction.followup.send("❌ 이 채널에서 카드 뽑기 대결이 진행 중입니다!", ephemeral=True)
                return

        # Deduct creator's bet
        coins_cog = self.bot.get_cog('CoinsCog')
        success = await coins_cog.remove_coins(
            interaction.user.id,
            interaction.guild.id,
            bet,
            "carddraw_bet",
            f"카드 뽑기 대결 베팅 ({bet}코인)"
        )

        if not success:
            await interaction.followup.send("❌ 베팅 처리에 실패했습니다!", ephemeral=True)
            return

        # Create game
        game_view = CardDrawView(
            self.bot,
            interaction.guild.id,
            channel_id,
            interaction.user.id,
            bet
        )

        # Set creator's name
        game_view.players[interaction.user.id].username = interaction.user.display_name

        self.active_games[channel_id] = game_view

        embed = game_view.create_battle_embed()

        # Send the initial message and store the message object
        message = await interaction.followup.send(embed=embed, view=game_view)
        game_view.message = message

        self.logger.info(
            f"{interaction.user}가 {bet}코인으로 카드 뽑기 대결을 시작했습니다",
            extra={'guild_id': interaction.guild.id}
        )

        # Auto-start after timeout if enough players
        await asyncio.sleep(60)  # 1 minute auto-start
        if (channel_id in self.active_games and
                self.active_games[channel_id].join_phase and
                len(self.active_games[channel_id].players) >= 2):
            try:
                await self.active_games[channel_id].start_battle_direct()
            except Exception as e:
                self.logger.error(f"Auto-start failed: {e}")


async def setup(bot):
    await bot.add_cog(CardDrawCog(bot))