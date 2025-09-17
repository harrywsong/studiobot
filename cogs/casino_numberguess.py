# cogs/casino_numberguess.py - Number Guessing Duel game
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import random
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger
from utils.config import (
    is_feature_enabled,
    is_server_configured
)


class GuessPlayer:
    """Player in number guessing duel"""

    def __init__(self, user_id: int, username: str, bet: int):
        self.user_id = user_id
        self.username = username
        self.bet = bet
        self.secret_number = None
        self.guesses_made = []
        self.guesses_received = []
        self.number_set = False
        self.is_winner = False
        self.turns_taken = 0


class NumberGuessView(discord.ui.View):
    """Interactive Number Guessing Duel view"""

    def __init__(self, bot, player1_id: int, player2_id: int, guild_id: int, bet: int):
        super().__init__(timeout=300)  # 5 minutes
        self.bot = bot
        self.guild_id = guild_id
        self.bet = bet
        self.player1 = GuessPlayer(player1_id, "플레이어 1", bet)
        self.player2 = GuessPlayer(player2_id, "플레이어 2", bet)
        self.setup_phase = True
        self.game_phase = False
        self.game_over = False
        self.current_turn = 1  # 1 = player1, 2 = player2
        self.max_turns = 10  # Max turns per player
        self.winner = None
        self.min_number = 1
        self.max_number = 100

    def get_current_player(self) -> GuessPlayer:
        """Get current player"""
        return self.player1 if self.current_turn == 1 else self.player2

    def get_opponent(self, player: GuessPlayer) -> GuessPlayer:
        """Get opponent of given player"""
        return self.player2 if player == self.player1 else self.player1

    def get_player_by_id(self, user_id: int) -> Optional[GuessPlayer]:
        """Get player by user ID"""
        if self.player1.user_id == user_id:
            return self.player1
        elif self.player2.user_id == user_id:
            return self.player2
        return None

    async def set_secret_number(self, interaction: discord.Interaction, user_id: int, number: int):
        """Handle setting secret number"""
        player = self.get_player_by_id(user_id)
        if not player:
            await interaction.response.send_message("❌ 이 게임의 참가자가 아닙니다!", ephemeral=True)
            return

        if player.number_set:
            await interaction.response.send_message("❌ 이미 숫자를 설정하셨습니다!", ephemeral=True)
            return

        if not (self.min_number <= number <= self.max_number):
            await interaction.response.send_message(f"❌ 숫자는 {self.min_number}-{self.max_number} 범위여야 합니다!",
                                                    ephemeral=True)
            return

        player.secret_number = number
        player.number_set = True

        await interaction.response.send_message(
            f"✅ 비밀 번호 **{number}**이 설정되었습니다!\n다른 플레이어가 설정할 때까지 기다려주세요.",
            ephemeral=True
        )

        # Check if both players set numbers
        if self.player1.number_set and self.player2.number_set:
            await self.start_guessing_phase(interaction)

    async def start_guessing_phase(self, interaction: discord.Interaction):
        """Start the guessing phase"""
        self.setup_phase = False
        self.game_phase = True

        # Update buttons for guessing
        self.clear_items()
        self.add_item(GuessButton())

        # Update player names with actual usernames
        user1 = self.bot.get_user(self.player1.user_id)
        user2 = self.bot.get_user(self.player2.user_id)

        if user1:
            self.player1.username = user1.display_name
        if user2:
            self.player2.username = user2.display_name

        embed = self.create_game_embed()
        try:
            await interaction.edit_original_response(embed=embed, view=self)
        except:
            # If edit fails, the message might be from a different interaction
            pass

    async def make_guess(self, interaction: discord.Interaction, user_id: int, guess: int):
        """Handle player guess"""
        if not self.game_phase:
            await interaction.response.send_message("❌ 아직 추리 단계가 시작되지 않았습니다!", ephemeral=True)
            return

        current_player = self.get_current_player()
        if user_id != current_player.user_id:
            await interaction.response.send_message("❌ 지금은 당신의 차례가 아닙니다!", ephemeral=True)
            return

        if not (self.min_number <= guess <= self.max_number):
            await interaction.response.send_message(f"❌ 추리는 {self.min_number}-{self.max_number} 범위여야 합니다!",
                                                    ephemeral=True)
            return

        if guess in current_player.guesses_made:
            await interaction.response.send_message("❌ 이미 추리한 숫자입니다!", ephemeral=True)
            return

        # Process guess
        opponent = self.get_opponent(current_player)
        current_player.guesses_made.append(guess)
        current_player.turns_taken += 1

        # Check if guess is correct
        if guess == opponent.secret_number:
            # Winner!
            current_player.is_winner = True
            self.winner = current_player
            self.game_over = True
            await self.end_game(interaction, f"🎉 {current_player.username}님이 정답을 맞췄습니다!")
            return

        # Give hint
        if guess < opponent.secret_number:
            hint = "⬆️ UP (더 큰 수)"
        else:
            hint = "⬇️ DOWN (더 작은 수)"

        # Record guess and hint for opponent
        opponent.guesses_received.append((guess, hint, current_player.turns_taken))

        # Check if max turns reached
        if current_player.turns_taken >= self.max_turns:
            # Check if opponent also reached max turns
            opponent_turns = opponent.turns_taken
            if opponent_turns >= self.max_turns:
                # Both players exhausted turns - tie
                self.game_over = True
                await self.end_game(interaction, "🤝 무승부! 둘 다 정답을 맞추지 못했습니다.")
                return
            elif opponent_turns == 0:
                # Give opponent their turns
                self.current_turn = 2 if self.current_turn == 1 else 1
            else:
                # Both had their turns, game over
                self.game_over = True
                await self.end_game(interaction, "😔 아무도 정답을 맞추지 못했습니다!")
                return
        else:
            # Switch turns
            self.current_turn = 2 if self.current_turn == 1 else 1

        # Send private feedback
        embed = discord.Embed(
            title="🎯 추리 결과",
            description=f"**당신의 추리:** {guess}\n**결과:** {hint}\n**남은 턴:** {self.max_turns - current_player.turns_taken}",
            color=discord.Color.orange()
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

        # Update main game display
        try:
            embed = self.create_game_embed()
            await interaction.edit_original_response(embed=embed, view=self)
        except:
            pass

    async def end_game(self, interaction: discord.Interaction, result_msg: str):
        """End the game and handle payouts"""
        self.game_over = True
        self.clear_items()

        # Handle coin payouts
        coins_cog = self.bot.get_cog('CoinsCog')

        if self.winner and coins_cog:
            # Winner gets both bets
            total_payout = self.player1.bet + self.player2.bet
            await coins_cog.add_coins(
                self.winner.user_id,
                self.guild_id,
                total_payout,
                "numberguess_win",
                f"숫자 맞추기 대결 승리 ({self.winner.turns_taken}턴)"
            )
        elif coins_cog:  # Tie - refund both
            await coins_cog.add_coins(
                self.player1.user_id,
                self.guild_id,
                self.player1.bet,
                "numberguess_tie",
                "숫자 맞추기 대결 무승부 환불"
            )
            await coins_cog.add_coins(
                self.player2.user_id,
                self.guild_id,
                self.player2.bet,
                "numberguess_tie",
                "숫자 맞추기 대결 무승부 환불"
            )

        embed = self.create_results_embed(result_msg)
        try:
            await interaction.edit_original_response(embed=embed, view=self)
        except:
            pass

    def create_setup_embed(self) -> discord.Embed:
        """Create setup phase embed"""
        embed = discord.Embed(
            title="🔢 숫자 맞추기 대결 - 설정 단계",
            description=f"**베팅금:** {self.bet:,}코인\n**범위:** {self.min_number}-{self.max_number}\n\n각자 비밀 번호를 설정해주세요!",
            color=discord.Color.blue()
        )

        # Show setup status
        status_list = []
        for player in [self.player1, self.player2]:
            status = "✅ 설정 완료" if player.number_set else "⏳ 설정 대기 중"
            status_list.append(f"{player.username}: {status}")

        embed.add_field(name="👥 설정 현황", value="\n".join(status_list), inline=False)

        embed.add_field(
            name="📋 게임 규칙",
            value=f"• 각자 {self.min_number}-{self.max_number} 범위의 비밀 번호 설정\n• 번갈아가며 상대방 숫자 추리\n• UP/DOWN 힌트 제공\n• 최대 {self.max_turns}턴까지 가능\n• 먼저 맞추는 사람이 승리",
            inline=False
        )

        return embed

    def create_game_embed(self) -> discord.Embed:
        """Create game phase embed"""
        current_player = self.get_current_player()

        embed = discord.Embed(
            title="🔢 숫자 맞추기 대결 - 추리 중",
            description=f"**현재 차례:** {current_player.username}\n**범위:** {self.min_number}-{self.max_number}\n**최대 턴:** {self.max_turns}",
            color=discord.Color.green()
        )

        # Show game status for both players
        for i, player in enumerate([self.player1, self.player2], 1):
            opponent = self.get_opponent(player)

            field_name = f"🎯 {player.username} (턴: {player.turns_taken}/{self.max_turns})"

            if player.guesses_made:
                recent_guesses = player.guesses_made[-3:]  # Last 3 guesses
                guess_str = ", ".join(str(g) for g in recent_guesses)
                if len(player.guesses_made) > 3:
                    guess_str = "... " + guess_str
            else:
                guess_str = "아직 추리하지 않음"

            # Show hints received
            hints_str = ""
            if opponent.guesses_received:
                recent_hints = opponent.guesses_received[-2:]  # Last 2 hints
                hint_parts = []
                for guess, hint, turn in recent_hints:
                    hint_parts.append(f"{guess} → {hint}")
                hints_str = "\n".join(hint_parts)
            else:
                hints_str = "힌트 없음"

            field_value = f"**최근 추리:** {guess_str}\n**받은 힌트:**\n{hints_str}"
            embed.add_field(name=field_name, value=field_value, inline=True)

        return embed

    def create_results_embed(self, result_msg: str) -> discord.Embed:
        """Create results embed"""
        if self.winner:
            title = f"🏆 {self.winner.username} 승리!"
            color = discord.Color.gold()
            total_payout = self.player1.bet + self.player2.bet
            description = f"{result_msg}\n\n**상금:** {total_payout:,}코인\n**소요 턴:** {self.winner.turns_taken}턴"
        else:
            title = "🤝 무승부"
            color = discord.Color.yellow()
            description = f"{result_msg}\n\n베팅금이 각자에게 반환됩니다."

        embed = discord.Embed(title=title, description=description, color=color)

        # Reveal both secret numbers
        embed.add_field(
            name="🔍 정답 공개",
            value=f"**{self.player1.username}의 숫자:** {self.player1.secret_number}\n**{self.player2.username}의 숫자:** {self.player2.secret_number}",
            inline=False
        )

        # Show final guess history
        for player in [self.player1, self.player2]:
            if player.guesses_made:
                guesses_str = ", ".join(str(g) for g in player.guesses_made)
                embed.add_field(
                    name=f"📝 {player.username}의 추리 기록",
                    value=guesses_str,
                    inline=False
                )

        return embed

    @discord.ui.button(label="🔢 숫자 설정", style=discord.ButtonStyle.primary)
    async def set_number_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.setup_phase:
            await interaction.response.send_message("❌ 설정 단계가 이미 끝났습니다!", ephemeral=True)
            return

        player = self.get_player_by_id(interaction.user.id)
        if not player:
            await interaction.response.send_message("❌ 이 게임의 참가자가 아닙니다!", ephemeral=True)
            return

        if player.number_set:
            await interaction.response.send_message("❌ 이미 숫자를 설정하셨습니다!", ephemeral=True)
            return

        # Show modal for number input
        modal = NumberSetModal(self, interaction.user.id)
        await interaction.response.send_modal(modal)

    async def on_timeout(self):
        """Handle game timeout"""
        if self.setup_phase or self.game_phase:
            # Refund both players
            coins_cog = self.bot.get_cog('CoinsCog')
            if coins_cog:
                await coins_cog.add_coins(
                    self.player1.user_id,
                    self.guild_id,
                    self.player1.bet,
                    "numberguess_timeout",
                    "숫자 맞추기 대결 시간 초과 환불"
                )
                await coins_cog.add_coins(
                    self.player2.user_id,
                    self.guild_id,
                    self.player2.bet,
                    "numberguess_timeout",
                    "숫자 맞추기 대결 시간 초과 환불"
                )


class NumberSetModal(discord.ui.Modal):
    """Modal for setting secret number"""

    def __init__(self, view: NumberGuessView, user_id: int):
        super().__init__(title="비밀 번호 설정")
        self.view = view
        self.user_id = user_id

        self.number_input = discord.ui.TextInput(
            label="비밀 번호",
            placeholder=f"{view.min_number}-{view.max_number} 범위의 숫자 입력...",
            min_length=1,
            max_length=3,
            required=True
        )
        self.add_item(self.number_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            number = int(self.number_input.value.strip())
            await self.view.set_secret_number(interaction, self.user_id, number)
        except ValueError:
            await interaction.response.send_message("❌ 올바른 숫자를 입력해주세요!", ephemeral=True)


class GuessButton(discord.ui.Button):
    """Button for making a guess"""

    def __init__(self):
        super().__init__(
            label="🎯 숫자 추리",
            style=discord.ButtonStyle.green,
            emoji="🔍"
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view

        if not view.game_phase:
            await interaction.response.send_message("❌ 아직 추리 단계가 시작되지 않았습니다!", ephemeral=True)
            return

        current_player = view.get_current_player()
        if interaction.user.id != current_player.user_id:
            await interaction.response.send_message("❌ 지금은 당신의 차례가 아닙니다!", ephemeral=True)
            return

        # Show modal for guess input
        modal = GuessModal(view, interaction.user.id)
        await interaction.response.send_modal(modal)


class GuessModal(discord.ui.Modal):
    """Modal for making a guess"""

    def __init__(self, view: NumberGuessView, user_id: int):
        super().__init__(title="숫자 추리")
        self.view = view
        self.user_id = user_id

        player = view.get_player_by_id(user_id)
        turns_left = view.max_turns - player.turns_taken

        self.guess_input = discord.ui.TextInput(
            label="추리할 숫자",
            placeholder=f"{view.min_number}-{view.max_number} 범위 (남은 턴: {turns_left})",
            min_length=1,
            max_length=3,
            required=True
        )
        self.add_item(self.guess_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            guess = int(self.guess_input.value.strip())
            await self.view.make_guess(interaction, self.user_id, guess)
        except ValueError:
            await interaction.response.send_message("❌ 올바른 숫자를 입력해주세요!", ephemeral=True)


class NumberGuessCog(commands.Cog):
    """Number Guessing Duel game"""

    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("숫자맞추기대결")
        self.pending_challenges: Dict[int, dict] = {}  # challenger_id -> challenge_info
        self.active_games: Dict[int, NumberGuessView] = {}  # channel_id -> game
        self.logger.info("숫자 맞추기 대결 게임 시스템이 초기화되었습니다.")

    async def validate_game(self, interaction: discord.Interaction, bet: int):
        """Validate game using casino base"""
        casino_base = self.bot.get_cog('CasinoBaseCog')
        if not casino_base:
            return False, "카지노 시스템을 찾을 수 없습니다!"

        return await casino_base.validate_game_start(
            interaction, "numberguess", bet, 30, 500
        )

    @app_commands.command(name="숫자맞추기", description="다른 플레이어와 숫자 맞추기 대결을 합니다")
    @app_commands.describe(
        opponent="대전할 상대방",
        bet="베팅 금액 (30-500코인)"
    )
    async def numberguess(
            self,
            interaction: discord.Interaction,
            opponent: discord.Member,
            bet: int = 100
    ):
        # Validate game using casino base
        casino_base = self.bot.get_cog('CasinoBaseCog')
        if casino_base:
            can_start, error_msg = await casino_base.validate_game_start(
                interaction, "numberguess", bet, 30, 500
            )
            if not can_start:
                await interaction.response.send_message(error_msg, ephemeral=True)
                return
        # Basic validation
        if opponent.id == interaction.user.id:
            await interaction.response.send_message("❌ 자기 자신과는 대결할 수 없습니다!", ephemeral=True)
            return

        if opponent.bot:
            await interaction.response.send_message("❌ 봇과는 대결할 수 없습니다!", ephemeral=True)
            return

        channel_id = interaction.channel.id

        # Check for existing game
        if channel_id in self.active_games:
            if not self.active_games[channel_id].game_over:
                await interaction.response.send_message("❌ 이 채널에서 이미 숫자 맞추기 게임이 진행 중입니다!", ephemeral=True)
                return
            else:
                del self.active_games[channel_id]

        # Validate both players' bets
        can_start, error_msg = await self.validate_game(interaction, bet)
        if not can_start:
            await interaction.response.send_message(error_msg, ephemeral=True)
            return

        # Check opponent's balance
        coins_cog = self.bot.get_cog('CoinsCog')
        if not coins_cog:
            await interaction.response.send_message("❌ 코인 시스템을 찾을 수 없습니다!", ephemeral=True)
            return

        opponent_balance = await coins_cog.get_balance(opponent.id, interaction.guild.id)
        if opponent_balance < bet:
            await interaction.response.send_message(
                f"❌ {opponent.display_name}님의 코인이 부족합니다! (필요: {bet:,}, 보유: {opponent_balance:,})", ephemeral=True)
            return

        # Create challenge
        challenge_embed = discord.Embed(
            title="🔢 숫자 맞추기 대결 신청",
            description=f"**신청자:** {interaction.user.mention}\n**상대:** {opponent.mention}\n**베팅금:** {bet:,}코인\n\n{opponent.mention}님, 대결을 수락하시겠습니까?",
            color=discord.Color.blue()
        )

        challenge_embed.add_field(
            name="📋 게임 규칙",
            value="• 각자 1-100 범위의 비밀 번호 설정\n• 번갈아가며 상대방 숫자 추리\n• UP/DOWN 힌트 제공\n• 최대 10턴까지 가능\n• 먼저 맞추는 사람이 승리",
            inline=False
        )

        challenge_view = NumberGuessChallenge(self, interaction.user.id, opponent.id, bet, channel_id)
        await interaction.response.send_message(embed=challenge_embed, view=challenge_view)

        self.logger.info(
            f"{interaction.user}가 {opponent}에게 {bet}코인으로 숫자 맞추기 대결을 신청했습니다",
            extra={'guild_id': interaction.guild.id}
        )


class NumberGuessChallenge(discord.ui.View):
    """Challenge acceptance view for number guessing duel"""

    def __init__(self, cog, challenger_id: int, opponent_id: int, bet: int, channel_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.challenger_id = challenger_id
        self.opponent_id = opponent_id
        self.bet = bet
        self.channel_id = channel_id

    @discord.ui.button(label="✅ 수락", style=discord.ButtonStyle.green)
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.opponent_id:
            await interaction.response.send_message("❌ 대전 상대방만 수락할 수 있습니다!", ephemeral=True)
            return

        # Deduct bets from both players
        coins_cog = self.cog.bot.get_cog('CoinsCog')

        # Deduct from challenger
        success1 = await coins_cog.remove_coins(
            self.challenger_id,
            interaction.guild.id,
            self.bet,
            "numberguess_bet",
            f"숫자 맞추기 대결 베팅 vs {interaction.user.display_name}"
        )

        # Deduct from opponent
        success2 = await coins_cog.remove_coins(
            self.opponent_id,
            interaction.guild.id,
            self.bet,
            "numberguess_bet",
            f"숫자 맞추기 대결 베팅 vs <@{self.challenger_id}>"
        )

        if not (success1 and success2):
            # Refund if either failed
            if success1:
                await coins_cog.add_coins(self.challenger_id, interaction.guild.id, self.bet, "numberguess_refund",
                                          "숫자 맞추기 베팅 환불")
            await interaction.response.send_message("❌ 베팅 처리에 실패했습니다!", ephemeral=True)
            return

        # Start the game
        game_view = NumberGuessView(
            self.cog.bot,
            self.challenger_id,
            self.opponent_id,
            interaction.guild.id,
            self.bet
        )

        # Set player names
        challenger = self.cog.bot.get_user(self.challenger_id)
        opponent = self.cog.bot.get_user(self.opponent_id)

        if challenger:
            game_view.player1.username = challenger.display_name
        if opponent:
            game_view.player2.username = opponent.display_name

        self.cog.active_games[self.channel_id] = game_view

        embed = game_view.create_setup_embed()
        await interaction.response.edit_message(embed=embed, view=game_view)

        # Disable this challenge view
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="❌ 거절", style=discord.ButtonStyle.red)
    async def decline_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.opponent_id:
            await interaction.response.send_message("❌ 대전 상대방만 거절할 수 있습니다!", ephemeral=True)
            return

        embed = discord.Embed(
            title="❌ 숫자 맞추기 대결 거절됨",
            description=f"{interaction.user.mention}님이 대결을 거절했습니다.",
            color=discord.Color.red()
        )

        await interaction.response.edit_message(embed=embed, view=None)

    async def on_timeout(self):
        """Handle challenge timeout"""
        embed = discord.Embed(
            title="⏰ 숫자 맞추기 대결 시간 초과",
            description="대결 신청이 시간 초과되었습니다.",
            color=discord.Color.orange()
        )


async def setup(bot):
    await bot.add_cog(NumberGuessCog(bot))
