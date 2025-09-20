# cogs/lottery.py
import discord
from discord.ext import commands, tasks
from discord import app_commands
import random
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
import json

from utils.logger import get_logger
from utils.config import get_server_setting


class LotteryEntry:
    """Represents a single lottery entry"""

    def __init__(self, user_id: int, numbers: List[int], entry_time: datetime):
        self.user_id = user_id
        self.numbers = sorted(numbers)  # Store sorted for easy comparison
        self.entry_time = entry_time


class LotterySystem:
    """Manages lottery state for a guild"""

    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.pot_amount = 0
        self.entries: Dict[int, LotteryEntry] = {}  # user_id -> entry
        self.draw_scheduled = None
        self.last_draw_time = None
        self.winning_numbers: List[int] = []
        self.last_winner_id = None
        self.last_prize_amount = 0


class LotteryCog(commands.Cog):
    """Casino fee-funded lottery system with responsible gaming features"""

    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("복권")
        self.guild_lotteries: Dict[int, LotterySystem] = {}
        self.lottery_interface_message = None  # Store the interface message
        self.lottery_channel_id = 1418763263721869403
        self._setup_completed = False  # Add flag to prevent duplicate setup


    async def setup_lottery_interface(self):
        """Setup the persistent lottery interface in the designated channel"""
        try:
            # Wait for bot to be ready
            if not self.bot.is_ready():
                self.logger.warning("Bot not ready, skipping lottery interface setup")
                return

            channel = self.bot.get_channel(self.lottery_channel_id)
            if not channel:
                self.logger.error(f"복권 채널을 찾을 수 없습니다: {self.lottery_channel_id}")
                return

            # Ensure we have permission to send messages
            if not channel.permissions_for(channel.guild.me).send_messages:
                self.logger.error(f"복권 채널에 메시지 전송 권한이 없습니다: {channel.name}")
                return

            # Get the guild ID directly from the channel object
            guild_id = channel.guild.id

            # Ensure lottery system exists for this guild
            lottery = self.get_lottery(guild_id)

            # Look for existing interface message
            self.lottery_interface_message = None
            async for message in channel.history(limit=20):
                if (message.author == self.bot.user and
                        message.embeds and
                        len(message.embeds) > 0 and
                        "복권 시스템" in message.embeds[0].title):
                    self.lottery_interface_message = message
                    self.logger.info(f"기존 복권 인터페이스 메시지 발견: {message.id}")
                    break

            # Create or update the interface
            embed = self.create_lottery_interface_embed(target_guild_id=guild_id)
            view = LotteryInterfaceView(self)

            if self.lottery_interface_message:
                try:
                    await self.lottery_interface_message.edit(embed=embed, view=view)
                    self.logger.info("기존 복권 인터페이스에 뷰를 연결하고 업데이트했습니다.")
                except discord.HTTPException as e:
                    self.logger.warning(f"기존 메시지 업데이트 실패, 새로 생성합니다: {e}")
                    # Delete the old message and create new one
                    try:
                        await self.lottery_interface_message.delete()
                    except:
                        pass
                    self.lottery_interface_message = None

            if not self.lottery_interface_message:
                # Create new interface
                try:
                    self.lottery_interface_message = await channel.send(embed=embed, view=view)
                    self.logger.info(f"새로운 복권 인터페이스를 생성했습니다: {self.lottery_interface_message.id}")
                except discord.HTTPException as e:
                    self.logger.error(f"복권 인터페이스 메시지 생성 실패: {e}")
                    return

        except Exception as e:
            self.logger.error(f"복권 인터페이스 설정 실패: {e}", exc_info=True)
    def create_lottery_interface_embed(self, target_guild_id: int = None) -> discord.Embed:
        """Create the main lottery interface embed"""
        # If no target guild specified, try to determine from channel context or use first available
        if target_guild_id is None:
            if self.lottery_interface_message:
                target_guild_id = self.lottery_interface_message.guild.id if self.lottery_interface_message.guild else None

            if target_guild_id is None and self.guild_lotteries:
                target_guild_id = next(iter(self.guild_lotteries.keys()))

        if target_guild_id and target_guild_id in self.guild_lotteries:
            lottery = self.guild_lotteries[target_guild_id]
        else:
            # Create a default display
            lottery = type('DefaultLottery', (), {
                'pot_amount': 0,
                'entries': {},
                'last_draw_time': None,
                'winning_numbers': [],
                'last_prize_amount': 0
            })()

        embed = discord.Embed(
            title="🎰 복권 시스템",
            description="카지노 게임 수수료와 패배 기여금으로 쌓인 복권 팟에 참가하세요!\n아래 버튼을 눌러 1-35 중 5개 번호를 선택하세요.",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc)
        )

        embed.add_field(
            name="💰 현재 팟",
            value=f"{lottery.pot_amount:,} 코인",
            inline=True
        )

        embed.add_field(
            name="👥 현재 참가자",
            value=f"{len(lottery.entries)}명",
            inline=True
        )

        min_pot = get_server_setting(target_guild_id, 'lottery_min_pot', 1000) # Use a consistent default
        embed.add_field(
            name="📊 최소 팟",
            value=f"{min_pot:,} 코인",
            inline=True
        )

        embed.add_field(
            name="💡 팟 충전 방식",
            value="• 크래시 승리 시: 5% 수수료\n• 카지노 패배 시: 베팅금의 50%\n• 자동 실시간 업데이트",
            inline=False
        )

        if lottery.last_draw_time:
            embed.add_field(
                name="📅 마지막 추첨",
                value=f"<t:{int(lottery.last_draw_time.timestamp())}:R>",
                inline=True
            )

        if lottery.winning_numbers:
            embed.add_field(
                name="🎯 지난 당첨 번호",
                value=" ".join(map(str, lottery.winning_numbers)),
                inline=True
            )

        if lottery.last_prize_amount > 0:
            embed.add_field(
                name="💎 지난 상금",
                value=f"{lottery.last_prize_amount:,} 코인",
                inline=True
            )

        embed.add_field(
            name="🏆 상금 구조",
            value="5개 일치: 팟의 500% (분할)\n4개 일치: 팟의 300% (분할)\n3개 일치: 팟의 100% (분할)",
            inline=False
        )

        embed.add_field(
            name="📋 참가 방법",
            value="1. '복권 참가하기' 버튼 클릭\n2. 1-35 범위에서 5개 번호 선택\n3. 관리자 추첨 대기\n\n⚠️ 한 번에 하나의 참가만 가능합니다!",
            inline=False
        )

        embed.set_footer(text="크래시 게임 수수료가 자동으로 팟에 추가됩니다")

        return embed

    async def update_lottery_interface(self, guild_id: int = None):
        """Update the lottery interface embed with current data"""
        if not self.lottery_interface_message:
            self.logger.warning("복권 인터페이스 메시지가 없어 업데이트를 건너뜁니다.")
            return

        try:
            # Use the specific guild_id if provided, otherwise determine from message context
            target_guild_id = guild_id
            if target_guild_id is None and self.lottery_interface_message.guild:
                target_guild_id = self.lottery_interface_message.guild.id

            if not target_guild_id:
                self.logger.warning("복권 인터페이스 업데이트용 guild_id를 확인할 수 없습니다.")
                return

            embed = self.create_lottery_interface_embed(target_guild_id)
            view = LotteryInterfaceView(self)

            # Add timestamp to show when last updated
            embed.set_footer(
                text=f"카지노 게임 수수료가 자동으로 팟에 추가됩니다 • 마지막 업데이트: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")

            await self.lottery_interface_message.edit(embed=embed, view=view)
            self.logger.debug(f"복권 인터페이스가 성공적으로 업데이트되었습니다 (길드: {target_guild_id}).")

        except discord.HTTPException as e:
            self.logger.error(f"복권 인터페이스 업데이트 실패: {e}")
            # Try to recreate the interface if edit failed
            if "Unknown Message" in str(e):
                self.logger.info("메시지가 삭제된 것으로 보입니다. 인터페이스를 재생성합니다.")
                self.lottery_interface_message = None
                await self.setup_lottery_interface()
        except Exception as e:
            self.logger.error(f"복권 인터페이스 업데이트 중 예외 발생: {e}", exc_info=True)

    @app_commands.command(name="복권인터페이스설정", description="복권 인터페이스를 수동으로 설정합니다 (관리자 전용)")
    async def setup_lottery_interface_command(self, interaction: discord.Interaction):
        """Manually setup lottery interface (admin only)"""
        # Check admin permissions
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⛔ 관리자만 사용할 수 있습니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            await self.setup_lottery_interface()
            embed = discord.Embed(
                title="✅ 복권 인터페이스 설정 완료",
                description="복권 인터페이스가 성공적으로 설정되었습니다.",
                color=discord.Color.green()
            )
        except Exception as e:
            self.logger.error(f"수동 복권 인터페이스 설정 실패: {e}", exc_info=True)
            embed = discord.Embed(
                title="⛔ 복권 인터페이스 설정 실패",
                description=f"설정 중 오류가 발생했습니다: {str(e)}",
                color=discord.Color.red()
            )

        await interaction.followup.send(embed=embed, ephemeral=True)
    @commands.Cog.listener()
    async def on_ready(self):
        """Run setup tasks once the bot is ready."""
        if not self._setup_completed:
            self.logger.info("복권 시스템 초기화 시작...")
            # Use asyncio.create_task instead of the loop decorator
            asyncio.create_task(self._initialize_lottery_system())

    async def _initialize_lottery_system(self):
        """Initialize the lottery system components"""
        try:
            # Wait a bit for bot to be fully ready
            await asyncio.sleep(2)

            # Create database tables
            await self._create_lottery_tables()

            # Load existing lottery states
            await self.load_lottery_states()

            # Setup the interface
            await self.setup_lottery_interface()

            self._setup_completed = True
            self.logger.info("복권 시스템 초기화 완료")

        except Exception as e:
            self.logger.error(f"복권 시스템 초기화 실패: {e}", exc_info=True)

    async def _create_lottery_tables(self):
        """Create lottery database tables"""
        if not self.bot.pool:
            self.logger.warning("데이터베이스 풀이 없어 테이블 생성을 건너뜁니다")
            return

        try:
            # Lottery state table
            await self.bot.pool.execute("""
                   CREATE TABLE IF NOT EXISTS lottery_state (
                       guild_id BIGINT PRIMARY KEY,
                       pot_amount BIGINT DEFAULT 0,
                       draw_scheduled TIMESTAMPTZ,
                       last_draw_time TIMESTAMPTZ,
                       winning_numbers TEXT,
                       last_winner_id BIGINT,
                       last_prize_amount BIGINT DEFAULT 0
                   );
               """)

            # Current entries table
            await self.bot.pool.execute("""
                   CREATE TABLE IF NOT EXISTS lottery_entries (
                       guild_id BIGINT,
                       user_id BIGINT,
                       numbers TEXT NOT NULL,
                       entry_time TIMESTAMPTZ DEFAULT NOW(),
                       PRIMARY KEY (guild_id, user_id)
                   );
               """)

            # Historical draws table
            await self.bot.pool.execute("""
                   CREATE TABLE IF NOT EXISTS lottery_history (
                       draw_id SERIAL PRIMARY KEY,
                       guild_id BIGINT NOT NULL,
                       draw_time TIMESTAMPTZ DEFAULT NOW(),
                       winning_numbers TEXT NOT NULL,
                       winner_id BIGINT,
                       prize_amount BIGINT NOT NULL,
                       total_entries INTEGER NOT NULL
                   );
               """)

            self.logger.info("복권 데이터베이스 테이블 생성 완료")

        except Exception as e:
            self.logger.error(f"복권 테이블 설정 실패: {e}", exc_info=True)

    async def load_lottery_states(self):
        """Load lottery states from database"""
        if not self.bot.pool:
            self.logger.warning("데이터베이스 풀이 없어 복권 상태 로드를 건너뜁니다")
            return

        try:
            states = await self.bot.pool.fetch("SELECT * FROM lottery_state")
            for state in states:
                guild_id = state['guild_id']
                lottery = LotterySystem(guild_id)
                lottery.pot_amount = state['pot_amount']
                lottery.draw_scheduled = state['draw_scheduled']
                lottery.last_draw_time = state['last_draw_time']
                lottery.last_winner_id = state['last_winner_id']
                lottery.last_prize_amount = state['last_prize_amount']

                if state['winning_numbers']:
                    lottery.winning_numbers = json.loads(state['winning_numbers'])

                # Load current entries
                entries = await self.bot.pool.fetch(
                    "SELECT * FROM lottery_entries WHERE guild_id = $1", guild_id)
                for entry in entries:
                    numbers = json.loads(entry['numbers'])
                    lottery.entries[entry['user_id']] = LotteryEntry(
                        entry['user_id'], numbers, entry['entry_time'])

                self.guild_lotteries[guild_id] = lottery

            self.logger.info(f"복권 상태 로드 완료: {len(self.guild_lotteries)}개 서버")

        except Exception as e:
            self.logger.error(f"복권 상태 로드 실패: {e}", exc_info=True)

    def get_lottery(self, guild_id: int) -> LotterySystem:
        """Get or create lottery system for guild"""
        if guild_id not in self.guild_lotteries:
            self.guild_lotteries[guild_id] = LotterySystem(guild_id)
        return self.guild_lotteries[guild_id]

    async def add_to_pot(self, guild_id: int, amount: int):
        """Add casino fees to lottery pot and update interface"""
        try:
            lottery = self.get_lottery(guild_id)
            lottery.pot_amount += amount

            # Update database
            await self.bot.pool.execute("""
                INSERT INTO lottery_state (guild_id, pot_amount)
                VALUES ($1, $2)
                ON CONFLICT (guild_id)
                DO UPDATE SET pot_amount = lottery_state.pot_amount + $2
            """, guild_id, amount)

            # Auto-update interface whenever pot changes, passing the specific guild_id
            await self.update_lottery_interface(guild_id)

            self.logger.info(f"복권 팟에 {amount} 코인 추가 (길드: {guild_id}) - 인터페이스 자동 업데이트됨")

        except Exception as e:
            self.logger.error(f"팟 추가 실패: {e}")

    def validate_lottery_numbers(self, numbers: List[int]) -> tuple[bool, str]:
        """Validate lottery number selection with debugging"""
        try:
            self.logger.info(f"번호 검증 시작: {numbers}")

            if not isinstance(numbers, list):
                self.logger.error(f"번호가 리스트가 아님: {type(numbers)}")
                return False, "잘못된 번호 형식입니다."

            if len(numbers) != 5:
                self.logger.error(f"번호 개수 오류: {len(numbers)} != 5")
                return False, "정확히 5개의 번호를 선택해야 합니다."

            if len(set(numbers)) != 5:
                self.logger.error(f"중복 번호 발견: {numbers}")
                return False, "중복된 번호는 선택할 수 없습니다."

            for i, num in enumerate(numbers):
                if not isinstance(num, int):
                    self.logger.error(f"번호 {i}가 정수가 아님: {num} ({type(num)})")
                    return False, f"번호는 정수여야 합니다: {num}"

                if not (1 <= num <= 35):
                    self.logger.error(f"번호 범위 오류: {num}")
                    return False, "번호는 1부터 35 사이여야 합니다."

            self.logger.info(f"번호 검증 성공: {numbers}")
            return True, ""

        except Exception as e:
            self.logger.error(f"번호 검증 중 오류: {e}", exc_info=True)
            return False, f"번호 검증 오류: {str(e)}"

    async def enter_lottery(self, user_id: int, guild_id: int, numbers: List[int]) -> tuple[bool, str]:
        """Enter user into lottery with detailed debugging"""
        try:
            self.logger.info(f"복권 참가 시작 - 사용자: {user_id}, 길드: {guild_id}, 번호: {numbers}")

            # Step 1: Get lottery system
            try:
                lottery = self.get_lottery(guild_id)
                self.logger.info(f"복권 시스템 가져오기 성공 - 현재 팟: {lottery.pot_amount}, 참가자: {len(lottery.entries)}")
            except Exception as e:
                self.logger.error(f"복권 시스템 가져오기 실패: {e}", exc_info=True)
                return False, f"복권 시스템 초기화 오류: {str(e)}"

            # Step 2: Check if user already entered
            try:
                if user_id in lottery.entries:
                    self.logger.info(f"사용자 {user_id} 이미 참가함")
                    return False, "이미 이번 추첨에 참가했습니다."
            except Exception as e:
                self.logger.error(f"사용자 중복 확인 오류: {e}", exc_info=True)
                return False, f"참가 상태 확인 오류: {str(e)}"

            # Step 3: Validate numbers
            try:
                valid, error_msg = self.validate_lottery_numbers(numbers)
                if not valid:
                    self.logger.info(f"번호 검증 실패: {error_msg}")
                    return False, error_msg
                self.logger.info(f"번호 검증 성공: {numbers}")
            except Exception as e:
                self.logger.error(f"번호 검증 오류: {e}", exc_info=True)
                return False, f"번호 검증 중 오류: {str(e)}"

            # Step 4: Check minimum pot
            try:
                min_pot = get_server_setting(guild_id, 'lottery_min_pot', 1000)
                if lottery.pot_amount < min_pot:
                    self.logger.info(f"팟 부족: {lottery.pot_amount} < {min_pot}")
                    return False, f"복권 팟이 최소 금액({min_pot:,} 코인)에 도달하지 않았습니다."
                self.logger.info(f"최소 팟 조건 만족: {lottery.pot_amount} >= {min_pot}")
            except Exception as e:
                self.logger.error(f"최소 팟 확인 오류: {e}", exc_info=True)
                return False, f"팟 확인 중 오류: {str(e)}"

            # Step 5: Create entry
            try:
                entry = LotteryEntry(user_id, numbers, datetime.now(timezone.utc))
                self.logger.info(f"복권 엔트리 생성 성공")
            except Exception as e:
                self.logger.error(f"복권 엔트리 생성 오류: {e}", exc_info=True)
                return False, f"참가 정보 생성 오류: {str(e)}"

            # Step 6: Add to memory first
            try:
                lottery.entries[user_id] = entry
                self.logger.info(f"메모리에 엔트리 추가 성공")
            except Exception as e:
                self.logger.error(f"메모리 엔트리 추가 오류: {e}", exc_info=True)
                return False, f"참가 정보 저장 오류: {str(e)}"

            # Step 7: Update database
            if self.bot.pool:
                try:
                    self.logger.info("데이터베이스 업데이트 시작")
                    await self.bot.pool.execute("""
                        INSERT INTO lottery_entries (guild_id, user_id, numbers)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (guild_id, user_id)
                        DO UPDATE SET numbers = $3, entry_time = NOW()
                    """, guild_id, user_id, json.dumps(numbers))

                    self.logger.info(f"데이터베이스 업데이트 성공")

                except Exception as db_error:
                    self.logger.error(f"데이터베이스 업데이트 실패: {db_error}", exc_info=True)
                    # Remove from memory if DB update failed
                    try:
                        if user_id in lottery.entries:
                            del lottery.entries[user_id]
                            self.logger.info("메모리에서 실패한 엔트리 제거")
                    except:
                        pass
                    return False, f"데이터베이스 저장 실패: {str(db_error)}"
            else:
                self.logger.warning("데이터베이스 풀이 없어 메모리에만 저장됩니다.")

            self.logger.info(f"복권 참가 완료 - 사용자: {user_id}")
            return True, f"복권에 성공적으로 참가했습니다! 선택 번호: {sorted(numbers)}"

        except Exception as e:
            self.logger.error(f"복권 참가 중 예상치 못한 오류: {e}", exc_info=True)

            # Clean up memory entry if it was added
            try:
                lottery = self.get_lottery(guild_id)
                if user_id in lottery.entries:
                    del lottery.entries[user_id]
                    self.logger.info("오류 후 메모리 정리 완료")
            except:
                pass

            return False, f"시스템 오류: {str(e)}"
    def calculate_matches(self, user_numbers: List[int], winning_numbers: List[int]) -> int:
        """Calculate number of matches"""
        return len(set(user_numbers) & set(winning_numbers))

    async def conduct_draw(self, guild_id: int) -> tuple[bool, str, Dict]:
        """Conduct lottery draw"""
        try:
            lottery = self.get_lottery(guild_id)

            if not lottery.entries:
                return False, "추첨 참가자가 없습니다.", {}

            if lottery.pot_amount <= 0:
                return False, "복권 팟이 비어있습니다.", {}

            # Generate winning numbers (5 numbers from 1-35)
            winning_numbers = sorted(random.sample(range(1, 36), 5))
            lottery.winning_numbers = winning_numbers

            # Find winners by match count (3+ matches win prizes)
            results = {}
            for match_count in range(3, 6):  # 3, 4, 5 matches win prizes
                results[match_count] = []

            for user_id, entry in lottery.entries.items():
                matches = self.calculate_matches(entry.numbers, winning_numbers)
                if matches >= 3:  # 3+ matches win prizes
                    results[matches].append((user_id, entry.numbers))

            # Calculate prizes (100% of pot distributed)
            prize_pool = lottery.pot_amount
            remaining_pot = 0

            # Calculate inflated prizes (create new coins for excitement)
            prize_multipliers = {
                5: 5.0,  # 500% of pot for perfect match
                4: 3.0,  # 300% of pot for 4 matches
                3: 1.0  # 100% of pot for 3 matches
            }

            winners = {}
            total_awarded = 0

            for match_count in [5, 4, 3]:
                if results[match_count]:
                    # Calculate total prize for this category
                    category_total_prize = int(prize_pool * prize_multipliers[match_count])
                    # Split among all winners in this category
                    per_winner = category_total_prize // len(results[match_count])

                    if per_winner > 0:
                        for user_id, numbers in results[match_count]:
                            winners[user_id] = {
                                'matches': match_count,
                                'numbers': numbers,
                                'prize': per_winner
                            }
                            total_awarded += per_winner

            # Award prizes
            coins_cog = self.bot.get_cog('CoinsCog')
            if coins_cog:
                for user_id, win_data in winners.items():
                    await coins_cog.add_coins(
                        user_id, guild_id, win_data['prize'],
                        "lottery_win", f"복권 당첨 ({win_data['matches']}개 일치)"
                    )

            # Record draw in history
            await self.bot.pool.execute("""
                INSERT INTO lottery_history (guild_id, winning_numbers, winner_id, prize_amount, total_entries)
                VALUES ($1, $2, $3, $4, $5)
            """, guild_id, json.dumps(winning_numbers),
                                        list(winners.keys())[0] if winners else None,
                                        total_awarded, len(lottery.entries))

            # Reset for next draw (pot goes to zero after full payout)
            lottery.pot_amount = 0
            lottery.entries.clear()
            lottery.last_draw_time = datetime.now(timezone.utc)
            lottery.last_prize_amount = total_awarded

            # Update database (pot reset to zero)
            await self.bot.pool.execute("""
                UPDATE lottery_state 
                SET pot_amount = 0, winning_numbers = $1, last_draw_time = NOW(), last_prize_amount = $2
                WHERE guild_id = $3
            """, json.dumps(winning_numbers), total_awarded, guild_id)

            # Clear entries
            await self.bot.pool.execute("DELETE FROM lottery_entries WHERE guild_id = $1", guild_id)

            draw_results = {
                'winning_numbers': winning_numbers,
                'winners': winners,
                'total_entries': len(lottery.entries),
                'total_awarded': total_awarded,
                'remaining_pot': 0
            }

            # Update the lottery interface after successful draw
            await self.update_lottery_interface()

            return True, "추첨이 완료되었습니다.", draw_results

        except Exception as e:
            self.logger.error(f"복권 추첨 실패: {e}")
            return False, f"추첨 중 오류가 발생했습니다: {e}", {}

    @app_commands.command(name="복권참가", description="복권에 참가합니다 (1-35 중 5개 번호 선택)")
    @app_commands.describe(
        n1="첫 번째 번호 (1-35)", n2="두 번째 번호", n3="세 번째 번호", n4="네 번째 번호", n5="다섯 번째 번호"
    )
    async def enter_lottery(self, interaction: discord.Interaction,
                            n1: int, n2: int, n3: int, n4: int, n5: int):
        """Enter the lottery with 5 numbers"""
        await interaction.response.defer(ephemeral=True)

        numbers = [n1, n2, n3, n4, n5]
        success, message = await self.enter_lottery(interaction.user.id, interaction.guild.id, numbers)

        if success:
            lottery = self.get_lottery(interaction.guild.id)
            embed = discord.Embed(
                title="🎫 복권 참가 완료!",
                description=message,
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="현재 팟", value=f"{lottery.pot_amount:,} 코인", inline=True)
            embed.add_field(name="총 참가자", value=f"{len(lottery.entries)}명", inline=True)
            embed.set_footer(text="행운을 빕니다!")

        else:
            embed = discord.Embed(
                title="❌ 복권 참가 실패",
                description=message,
                color=discord.Color.red()
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="복권상태", description="현재 복권 상태를 확인합니다")
    async def lottery_status(self, interaction: discord.Interaction):
        """Check lottery status"""
        lottery = self.get_lottery(interaction.guild.id)

        embed = discord.Embed(
            title="🎲 복권 상태",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc)
        )

        embed.add_field(name="💰 현재 팟", value=f"{lottery.pot_amount:,} 코인", inline=True)
        embed.add_field(name="👥 참가자 수", value=f"{len(lottery.entries)}명", inline=True)

        min_pot = get_server_setting(interaction.guild.id, 'lottery_min_pot', 1000)
        embed.add_field(name="📊 최소 팟", value=f"{min_pot:,} 코인", inline=True)

        if lottery.last_draw_time:
            embed.add_field(
                name="📅 마지막 추첨",
                value=f"<t:{int(lottery.last_draw_time.timestamp())}:R>",
                inline=True
            )

        if lottery.winning_numbers:
            embed.add_field(
                name="🎯 지난 당첨 번호",
                value=" ".join(map(str, lottery.winning_numbers)),
                inline=True
            )

        if lottery.last_prize_amount > 0:
            embed.add_field(
                name="💎 지난 상금",
                value=f"{lottery.last_prize_amount:,} 코인",
                inline=True
            )

        # Prize structure info
        embed.add_field(
            name="🏆 상금 구조",
            value="5개 일치: 팟의 500% (분할)\n4개 일치: 팟의 300% (분할)\n3개 일치: 팟의 100% (분할)\n*가상 화폐 생성으로 높은 보상*",
            inline=False
        )

        embed.set_footer(text="크래시 게임 수수료로 팟이 쌓입니다")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="복권디버그", description="복권 시스템 디버깅 (관리자 전용)")
    async def debug_lottery(self, interaction: discord.Interaction):
        """Debug lottery system"""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("관리자만 사용할 수 있습니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        debug_info = []

        try:
            # Test 1: Basic system check
            debug_info.append("시스템 체크:")
            debug_info.append(f"- Bot ready: {self.bot.is_ready()}")
            debug_info.append(f"- Database pool: {'있음' if self.bot.pool else '없음'}")
            debug_info.append(f"- Guild lotteries: {len(self.guild_lotteries)}")

            # Test 2: Guild lottery check
            try:
                lottery = self.get_lottery(interaction.guild.id)
                debug_info.append(f"- 길드 복권 시스템: 정상")
                debug_info.append(f"- 현재 팟: {lottery.pot_amount}")
                debug_info.append(f"- 현재 참가자: {len(lottery.entries)}")
            except Exception as e:
                debug_info.append(f"- 길드 복권 시스템: 오류 ({e})")

            # Test 3: Database connection
            if self.bot.pool:
                try:
                    result = await self.bot.pool.fetchval("SELECT 1")
                    debug_info.append(f"- DB 연결: 정상")
                except Exception as e:
                    debug_info.append(f"- DB 연결: 오류 ({e})")

            # Test 4: Settings check
            try:
                min_pot = get_server_setting(interaction.guild.id, 'lottery_min_pot', 1000)
                debug_info.append(f"- 최소 팟 설정: {min_pot}")
            except Exception as e:
                debug_info.append(f"- 설정 확인: 오류 ({e})")

            # Test 5: Number validation
            try:
                valid, msg = self.validate_lottery_numbers([1, 2, 3, 4, 5])
                debug_info.append(f"- 번호 검증: {'정상' if valid else '오류'} ({msg})")
            except Exception as e:
                debug_info.append(f"- 번호 검증: 오류 ({e})")

        except Exception as e:
            debug_info.append(f"디버그 중 오류: {e}")

        embed = discord.Embed(
            title="복권 시스템 디버그",
            description="\n".join(debug_info),
            color=discord.Color.blue()
        )

        await interaction.followup.send(embed=embed, ephemeral=True)
    @app_commands.command(name="복권추첨", description="복권 추첨을 실시합니다 (관리자 전용)")
    async def conduct_lottery_draw(self, interaction: discord.Interaction):
        """Conduct lottery draw (admin only)"""
        # Check admin permissions
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ 관리자만 사용할 수 있습니다.", ephemeral=True)
            return

        await interaction.response.defer()

        success, message, results = await self.conduct_draw(interaction.guild.id)

        if not success:
            embed = discord.Embed(title="❌ 추첨 실패", description=message, color=discord.Color.red())
            await interaction.followup.send(embed=embed)
            return

        # Create results embed
        embed = discord.Embed(
            title="🎊 복권 추첨 결과!",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc)
        )

        winning_numbers = results['winning_numbers']
        embed.add_field(
            name="🎯 당첨 번호",
            value=" ".join(f"**{num}**" for num in winning_numbers),
            inline=False
        )

        embed.add_field(name="👥 총 참가자", value=f"{results['total_entries']}명", inline=True)
        embed.add_field(name="💰 총 상금", value=f"{results['total_awarded']:,} 코인", inline=True)
        embed.add_field(name="💵 남은 팟", value=f"{results['remaining_pot']:,} 코인", inline=True)

        # Winner details
        winners = results['winners']
        if winners:
            winner_text = []
            for user_id, win_data in winners.items():
                user = self.bot.get_user(user_id)
                username = user.display_name if user else f"사용자 {user_id}"
                winner_text.append(
                    f"🎉 {username}: {win_data['matches']}개 일치 - {win_data['prize']:,} 코인"
                )

            embed.add_field(
                name="🏆 당첨자",
                value="\n".join(winner_text[:10]) + ("..." if len(winner_text) > 10 else ""),
                inline=False
            )
        else:
            embed.add_field(name="😢 당첨자", value="이번 추첨에는 당첨자가 없습니다.", inline=False)

        embed.set_footer(text="다음 추첨을 위해 새로 참가해주세요!")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="복권내역", description="복권 추첨 이력을 확인합니다")
    async def lottery_history(self, interaction: discord.Interaction):
        """View lottery history"""
        try:
            history = await self.bot.pool.fetch("""
                SELECT * FROM lottery_history 
                WHERE guild_id = $1 
                ORDER BY draw_time DESC 
                LIMIT 5
            """, interaction.guild.id)

            embed = discord.Embed(
                title="📚 복권 추첨 이력",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )

            if not history:
                embed.description = "아직 추첨 이력이 없습니다."
            else:
                for i, draw in enumerate(history, 1):
                    winning_nums = json.loads(draw['winning_numbers'])
                    winner_text = "당첨자 없음"

                    if draw['winner_id']:
                        user = self.bot.get_user(draw['winner_id'])
                        winner_text = user.display_name if user else f"사용자 {draw['winner_id']}"

                    embed.add_field(
                        name=f"🎲 추첨 #{draw['draw_id']}",
                        value=f"**당첨 번호:** {' '.join(map(str, winning_nums))}\n"
                              f"**당첨자:** {winner_text}\n"
                              f"**상금:** {draw['prize_amount']:,} 코인\n"
                              f"**참가자:** {draw['total_entries']}명\n"
                              f"**날짜:** <t:{int(draw['draw_time'].timestamp())}:f>",
                        inline=False
                    )

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            self.logger.error(f"복권 이력 조회 실패: {e}")
            await interaction.response.send_message("이력 조회 중 오류가 발생했습니다.", ephemeral=True)


class LotteryEntryModal(discord.ui.Modal, title="복권 번호 선택"):
    """Modal for entering lottery numbers"""

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

        self.number1 = discord.ui.TextInput(
            label="첫 번째 번호 (1-35)",
            placeholder="1",
            min_length=1,
            max_length=2,
        )
        self.add_item(self.number1)

        self.number2 = discord.ui.TextInput(
            label="두 번째 번호 (1-35)",
            placeholder="2",
            min_length=1,
            max_length=2,
        )
        self.add_item(self.number2)

        self.number3 = discord.ui.TextInput(
            label="세 번째 번호 (1-35)",
            placeholder="3",
            min_length=1,
            max_length=2,
        )
        self.add_item(self.number3)

        self.number4 = discord.ui.TextInput(
            label="네 번째 번호 (1-35)",
            placeholder="4",
            min_length=1,
            max_length=2,
        )
        self.add_item(self.number4)

        self.number5 = discord.ui.TextInput(
            label="다섯 번째 번호 (1-35)",
            placeholder="5",
            min_length=1,
            max_length=2,
        )
        self.add_item(self.number5)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)

            # Parse numbers with better error handling
            numbers = []
            for i, field in enumerate([self.number1, self.number2, self.number3, self.number4, self.number5], 1):
                try:
                    value = field.value.strip()
                    if not value:
                        await interaction.followup.send(f"번호 {i}가 비어있습니다.", ephemeral=True)
                        return

                    num = int(value)
                    if not (1 <= num <= 35):
                        await interaction.followup.send(f"번호는 1부터 35 사이여야 합니다. (입력된 값: {num})", ephemeral=True)
                        return

                    numbers.append(num)
                except ValueError:
                    await interaction.followup.send(f"'{field.value}'는 유효한 숫자가 아닙니다.", ephemeral=True)
                    return

            # Check for duplicates
            if len(set(numbers)) != len(numbers):
                await interaction.followup.send("중복된 번호는 선택할 수 없습니다.", ephemeral=True)
                return

            # Ensure we have a valid guild
            if not interaction.guild:
                await interaction.followup.send("서버에서만 사용할 수 있습니다.", ephemeral=True)
                return

            # Enter lottery with additional error checking
            try:
                success, message = await self.cog.enter_lottery(
                    interaction.user.id,
                    interaction.guild.id,
                    numbers
                )
            except Exception as lottery_error:
                self.cog.logger.error(f"복권 참가 함수에서 오류: {lottery_error}", exc_info=True)
                await interaction.followup.send("복권 시스템에 일시적인 오류가 있습니다. 잠시 후 다시 시도해주세요.", ephemeral=True)
                return

            if success:
                try:
                    lottery = self.cog.get_lottery(interaction.guild.id)
                    embed = discord.Embed(
                        title="🎫 복권 참가 완료!",
                        description=message,
                        color=discord.Color.green(),
                        timestamp=datetime.now(timezone.utc)
                    )
                    embed.add_field(name="현재 팟", value=f"{lottery.pot_amount:,} 코인", inline=True)
                    embed.add_field(name="총 참가자", value=f"{len(lottery.entries)}명", inline=True)
                    embed.set_footer(text="행운을 빕니다!")

                    await interaction.followup.send(embed=embed, ephemeral=True)

                    # Update the main lottery interface safely
                    try:
                        await self.cog.update_lottery_interface(interaction.guild.id)
                    except Exception as update_error:
                        self.cog.logger.error(f"로또 인터페이스 업데이트 오류: {update_error}")
                        # Don't fail the whole operation if interface update fails

                except Exception as display_error:
                    self.cog.logger.error(f"성공 메시지 표시 오류: {display_error}", exc_info=True)
                    # Still send a basic success message
                    await interaction.followup.send("복권 참가가 완료되었습니다!", ephemeral=True)
            else:
                embed = discord.Embed(
                    title="⌘ 복권 참가 실패",
                    description=message,
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed, ephemeral=True)

        except discord.errors.InteractionResponded:
            # Interaction was already responded to
            self.cog.logger.warning("인터랙션이 이미 응답되었습니다.")

        except discord.errors.NotFound:
            # Interaction expired or not found
            self.cog.logger.warning("인터랙션을 찾을 수 없습니다 (만료됨)")

        except Exception as e:
            self.cog.logger.error(f"복권 참가 모달에서 예상치 못한 오류: {e}", exc_info=True)

            # Try to send error message if interaction hasn't been responded to
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "복권 참가 중 오류가 발생했습니다. 관리자에게 문의해주세요.",
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send(
                        "복권 참가 중 오류가 발생했습니다. 관리자에게 문의해주세요.",
                        ephemeral=True
                    )
            except:
                # If we can't even send an error message, just log it
                self.cog.logger.error("오류 메시지 전송도 실패했습니다.")
                pass
class LotteryInterfaceView(discord.ui.View):
    """Persistent view for the main lottery interface"""

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="🎲 복권 참가하기",
        style=discord.ButtonStyle.primary,
        emoji="🎫",
        custom_id="lottery_enter_button"
    )
    async def enter_lottery(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if user already entered
        lottery = self.cog.get_lottery(interaction.guild.id)
        if interaction.user.id in lottery.entries:
            await interaction.response.send_message("이미 이번 추첨에 참가했습니다.", ephemeral=True)
            return

        # Check minimum pot
        min_pot = get_server_setting(interaction.guild.id, 'lottery_min_pot', 1000)
        if lottery.pot_amount < min_pot:
            await interaction.response.send_message(
                f"복권 팟이 최소 금액({min_pot:,} 코인)에 도달하지 않았습니다.",
                ephemeral=True
            )
            return

        modal = LotteryEntryModal(self.cog)
        await interaction.response.send_modal(modal)
# Function to be called from casino games to add fees to lottery pot
async def add_casino_fee_to_lottery(bot, guild_id: int, fee_amount: int):
    """Add casino game fees to lottery pot"""
    lottery_cog = bot.get_cog('LotteryCog')
    if lottery_cog:
        await lottery_cog.add_to_pot(guild_id, fee_amount)


async def setup(bot):
    await bot.add_cog(LotteryCog(bot))