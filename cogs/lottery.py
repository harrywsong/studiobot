# Enhanced lottery.py with robust interface management
import discord
from discord.ext import commands, tasks
from discord import app_commands
import random
import asyncio
from datetime import datetime, timezone, timedelta, time
from typing import Dict, List, Optional
import json
import pytz

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
        self.lottery_interface_message: Optional[discord.Message] = None
        self.lottery_channel_id = 1418763263721869403
        self._interface_setup_complete = False

        # Schedule the full initialization sequence
        self.bot.loop.create_task(self.initialize())

    async def initialize(self):
        """Comprehensive initialization for both bot startup and cog reload"""
        try:
            # Wait for the bot to be fully ready
            await self.bot.wait_until_ready()
            self.logger.info("Bot is ready. Starting lottery system initialization...")

            # Load saved states from database
            self.logger.info("Loading saved lottery states from database...")
            await self.load_lottery_states()

            # Always ensure the lottery interface is posted and current
            self.logger.info("Setting up lottery interface...")
            await self.ensure_lottery_interface()

            # Start the draw task with better error handling
            self.logger.info("Starting automated draw task...")
            try:
                if self.daily_lottery_draw.is_running():
                    self.logger.info("Task was already running, cancelling first...")
                    self.daily_lottery_draw.cancel()
                    await asyncio.sleep(1)  # Wait for cleanup

                self.daily_lottery_draw.start()
                await asyncio.sleep(2)  # Give it time to start

                if self.daily_lottery_draw.is_running():
                    self.logger.info("✅ Daily lottery draw task started successfully")
                else:
                    self.logger.error("❌ Daily lottery draw task failed to start")

            except Exception as task_error:
                self.logger.error(f"Error starting lottery task: {task_error}", exc_info=True)

            self._interface_setup_complete = True
            self.logger.info("Lottery system initialization completed")

            # Debug current status
            await self.debug_automation_status()

        except Exception as e:
            self.logger.error(f"Critical error during lottery initialization: {e}", exc_info=True)

    async def test_lottery_task(self):
        """Test if the lottery task is properly configured"""
        self.logger.info("Testing lottery task configuration...")

        # Check if times are valid
        loop_times = self.daily_lottery_draw.time
        self.logger.info(f"Configured loop times: {loop_times}")

        # Check next iteration
        if self.daily_lottery_draw.next_iteration:
            next_time = self.daily_lottery_draw.next_iteration
            self.logger.info(f"Next iteration scheduled for: {next_time}")

            # Check if next iteration is reasonable (not too far in future)
            now = datetime.now(timezone.utc)
            time_diff = next_time - now
            self.logger.info(f"Time until next iteration: {time_diff}")

            if time_diff.total_seconds() > 86400:  # More than 24 hours
                self.logger.warning("Next iteration is more than 24 hours away - this might be wrong")
        else:
            self.logger.warning("No next iteration scheduled")

    @app_commands.command(name="복권테스트", description="복권 시스템 테스트 (관리자 전용)")
    async def test_lottery_system(self, interaction: discord.Interaction):
        """Test lottery system configuration"""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⛔ 관리자만 사용할 수 있습니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        await self.test_lottery_task()

        embed = discord.Embed(
            title="🧪 복권 시스템 테스트 완료",
            description="테스트 결과가 로그에 기록되었습니다.",
            color=discord.Color.blue()
        )

        await interaction.followup.send(embed=embed, ephemeral=True)

    async def ensure_lottery_interface(self):
        """Ensure the lottery interface is posted and current (handles both new and existing)"""
        try:
            channel = self.bot.get_channel(self.lottery_channel_id)
            if not channel:
                self.logger.error(f"Lottery channel not found: {self.lottery_channel_id}")
                return

            # Check permissions
            if not channel.permissions_for(channel.guild.me).send_messages:
                self.logger.error(f"No permission to send messages in lottery channel: {channel.name}")
                return

            guild_id = channel.guild.id
            lottery = self.get_lottery(guild_id)

            # Look for existing interface message in recent history
            existing_message = None
            try:
                async for message in channel.history(limit=50):  # Check more messages
                    if (message.author == self.bot.user and
                            message.embeds and
                            len(message.embeds) > 0 and
                            "복권 시스템" in message.embeds[0].title):
                        existing_message = message
                        self.logger.info(f"Found existing lottery interface: {message.id}")
                        break
            except Exception as e:
                self.logger.warning(f"Error searching for existing interface: {e}")

            # Create new embed and view
            embed = self.create_lottery_interface_embed(target_guild_id=guild_id)
            view = LotteryInterfaceView(self)

            # Update existing message or create new one
            if existing_message:
                try:
                    await existing_message.edit(embed=embed, view=view)
                    self.lottery_interface_message = existing_message
                    self.logger.info("Successfully updated existing lottery interface")
                    return
                except discord.HTTPException as e:
                    self.logger.warning(f"Failed to update existing message, creating new one: {e}")
                    # Try to delete the old message
                    try:
                        await existing_message.delete()
                    except:
                        pass

            # Create new interface message
            try:
                self.lottery_interface_message = await channel.send(embed=embed, view=view)
                self.logger.info(f"Created new lottery interface: {self.lottery_interface_message.id}")
            except discord.HTTPException as e:
                self.logger.error(f"Failed to create lottery interface: {e}")

        except Exception as e:
            self.logger.error(f"Error ensuring lottery interface: {e}", exc_info=True)

    def cog_unload(self):
        """Clean up when cog is unloaded"""
        if self.daily_lottery_draw.is_running():
            self.daily_lottery_draw.cancel()
            self.logger.info("Daily lottery draw task cancelled due to cog unload")

    @commands.Cog.listener()
    async def on_ready(self):
        """Additional setup when bot becomes ready (handles reconnections)"""
        if not self._interface_setup_complete:
            self.logger.info("Bot reconnected, ensuring lottery interface...")
            await self.ensure_lottery_interface()

    async def setup_lottery_interface(self):
        """Legacy method - now redirects to ensure_lottery_interface for compatibility"""
        await self.ensure_lottery_interface()

    @tasks.loop(
        time=[
            time(hour=5, minute=0),  # 12:00 AM EST (UTC-5) / 1:00 AM EDT (UTC-4)
            time(hour=11, minute=0),  # 6:00 AM EST / 7:00 AM EDT
            time(hour=17, minute=0),  # 12:00 PM EST / 1:00 PM EDT
            time(hour=23, minute=0),  # 6:00 PM EST / 7:00 PM EDT
        ]
    )
    async def daily_lottery_draw(self):
        """Automatically conduct lottery draws at specified UTC times"""
        try:
            current_utc = datetime.now(timezone.utc)
            self.logger.info(f"=== AUTOMATED LOTTERY DRAW TRIGGERED AT {current_utc} ===")
            self.logger.info(f"Starting automated daily lottery draw...")

            # Process all guilds with lottery systems
            for guild_id, lottery in self.guild_lotteries.items():
                try:
                    # Skip if no participants
                    if not lottery.entries:
                        self.logger.info(f"No participants for guild {guild_id}, skipping draw")
                        await self.repost_lottery_interface(guild_id)
                        continue

                    # Skip if pot is below minimum
                    min_pot = get_server_setting(guild_id, 'lottery_min_pot', 1000)
                    if lottery.pot_amount < min_pot:
                        self.logger.info(f"Pot below minimum for guild {guild_id}, skipping draw")
                        await self.repost_lottery_interface(guild_id)
                        continue

                    self.logger.info(f"Conducting automated draw for guild {guild_id}")

                    # Conduct the draw
                    success, message, results = await self.conduct_draw(guild_id)

                    if success:
                        # Send results to lottery channel
                        channel = self.bot.get_channel(self.lottery_channel_id)
                        if channel and channel.guild.id == guild_id:

                            # Create results embed
                            embed = discord.Embed(
                                title="🎊 자동 복권 추첨 결과! (일일 추첨)",
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

                            embed.add_field(
                                name="⏰ 다음 자동 추첨",
                                value="6시간 후",
                                inline=False
                            )
                            embed.set_footer(text="매일 자동 추첨! 새로 참가해주세요!")

                            # Send the results
                            await channel.send(embed=embed)
                            self.logger.info(f"Sent automated draw results for guild {guild_id}")

                        # Always repost the interface after draw
                        await self.repost_lottery_interface(guild_id)

                    else:
                        self.logger.warning(f"Automated draw failed for guild {guild_id}: {message}")
                        # Still repost interface to keep it latest
                        await self.repost_lottery_interface(guild_id)

                except Exception as e:
                    self.logger.error(f"Error in automated draw for guild {guild_id}: {e}", exc_info=True)
                    # Try to repost interface even if draw failed
                    try:
                        await self.repost_lottery_interface(guild_id)
                    except:
                        pass

            self.logger.info("Completed automated daily lottery draws")

        except Exception as e:
            self.logger.error(f"Critical error in daily lottery draw task: {e}", exc_info=True)

    @daily_lottery_draw.before_loop
    async def before_daily_lottery_draw(self):
        """Wait for bot to be ready before starting the daily draw task"""
        await self.bot.wait_until_ready()
        self.logger.info("Daily lottery draw task is ready to start")

    @daily_lottery_draw.error
    async def daily_lottery_draw_error(self, error):
        """Handle errors in the daily lottery draw task"""
        self.logger.error(f"Error in daily_lottery_draw task: {error}", exc_info=True)

    async def repost_lottery_interface(self, guild_id: int):
        """Delete the old lottery interface and create a new one as the latest message"""
        try:
            # Get the lottery channel
            channel = self.bot.get_channel(self.lottery_channel_id)
            if not channel:
                self.logger.error(f"복권 채널을 찾을 수 없습니다: {self.lottery_channel_id}")
                return

            # Ensure we have permission to send messages
            if not channel.permissions_for(channel.guild.me).send_messages:
                self.logger.error(f"복권 채널에 메시지 전송 권한이 없습니다: {channel.name}")
                return

            # Delete the old interface message if it exists
            if self.lottery_interface_message:
                try:
                    await self.lottery_interface_message.delete()
                    self.logger.info(f"기존 복권 인터페이스 메시지 삭제: {self.lottery_interface_message.id}")
                except discord.HTTPException as e:
                    self.logger.warning(f"기존 메시지 삭제 실패 (이미 삭제되었을 수 있음): {e}")
                except Exception as e:
                    self.logger.error(f"기존 메시지 삭제 중 오류: {e}")

            # Create new interface embed and view
            embed = self.create_lottery_interface_embed(target_guild_id=guild_id)
            view = LotteryInterfaceView(self)

            # Send the new interface message
            try:
                self.lottery_interface_message = await channel.send(embed=embed, view=view)
                self.logger.info(f"새로운 복권 인터페이스를 생성했습니다: {self.lottery_interface_message.id}")
            except discord.HTTPException as e:
                self.logger.error(f"복권 인터페이스 메시지 생성 실패: {e}")
                return

        except Exception as e:
            self.logger.error(f"복권 인터페이스 재게시 실패: {e}", exc_info=True)

    def create_lottery_interface_embed(self, target_guild_id: int = None) -> discord.Embed:
        """Create the main lottery interface embed with fixed automation display"""
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

        min_pot = get_server_setting(target_guild_id, 'lottery_min_pot', 1000)  # Use a consistent default
        embed.add_field(
            name="📊 최소 팟",
            value=f"{min_pot:,} 코인",
            inline=True
        )

        # Simplified automation status check
        is_automated = self.daily_lottery_draw.is_running()

        automation_status = "🟢 자동 추첨 활성화" if is_automated else "🔴 수동 추첨만"

        embed.add_field(
            name="🤖 추첨 시스템",
            value=f"{automation_status}\n{'6시간마다 자동 추첨' if is_automated else '관리자 수동 추첨'}",
            inline=True
        )

        embed.add_field(
            name="💡 팟 충전 방식",
            value="• 크래시 승리 시: 5% 수수료\n• 카지노 패배 시: 베팅금의 10%\n• 자동 실시간 업데이트",
            inline=True
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

        # Show next automated draw time only if automation is active
        if is_automated:
            try:
                # Calculate next draw time in EST/EDT
                est = pytz.timezone('US/Eastern')
                now_utc = datetime.now(timezone.utc)
                now_est = now_utc.astimezone(est)

                # Draw times in Eastern (12 AM, 6 AM, 12 PM, 6 PM)
                # Convert to UTC hours for comparison
                draw_times_utc = [5, 11, 17, 23]  # UTC equivalents

                current_utc_hour = now_utc.hour
                next_draw_hour_utc = None

                # Find next draw time
                for hour in draw_times_utc:
                    if hour > current_utc_hour:
                        next_draw_hour_utc = hour
                        break

                # If no draw time left today, use tomorrow's first draw
                if next_draw_hour_utc is None:
                    next_draw_hour_utc = draw_times_utc[0]  # 5 UTC (midnight EST)
                    next_draw_time_utc = now_utc.replace(hour=next_draw_hour_utc, minute=0, second=0,
                                                         microsecond=0) + timedelta(days=1)
                else:
                    next_draw_time_utc = now_utc.replace(hour=next_draw_hour_utc, minute=0, second=0, microsecond=0)

                embed.add_field(
                    name="⏰ 다음 자동 추첨",
                    value=f"<t:{int(next_draw_time_utc.timestamp())}:R>\n({next_draw_time_utc.strftime('%H:%M UTC')})",
                    inline=True
                )

            except Exception as e:
                self.logger.error(f"Next draw time calculation failed: {e}", exc_info=True)
                embed.add_field(
                    name="⏰ 다음 자동 추첨",
                    value="6시간마다 자동 추첨",
                    inline=True
                )
        else:
            # Show manual draw information when automation is off
            embed.add_field(
                name="⏰ 추첨 방식",
                value="수동 추첨만 가능\n관리자가 직접 실행",
                inline=True
            )

        embed.add_field(
            name="🏆 상금 구조",
            value="5개 일치: 팟의 60% (분할)\n4개 일치: 팟의 30% (분할)\n3개 일치: 팟의 10% (분할)\n\n💡 당첨자가 없으면 팟이 다음 추첨으로 이월됩니다",
            inline=False
        )

        embed.add_field(
            name="📋 참가 방법",
            value="1. '복권 참가하기' 버튼 클릭\n2. 1-35 범위에서 5개 번호 선택\n3. 자동/수동 추첨 대기\n\n⚠️ 한 번에 하나의 참가만 가능합니다!",
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
                text=f"크래시 게임 수수료가 자동으로 팟에 추가됩니다 • 마지막 업데이트: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")

            await self.lottery_interface_message.edit(embed=embed, view=view)
            self.logger.debug(f"복권 인터페이스가 성공적으로 업데이트되었습니다 (길드: {target_guild_id}).")

        except discord.HTTPException as e:
            self.logger.error(f"복권 인터페이스 업데이트 실패: {e}")
            # Try to recreate the interface if edit failed
            if "Unknown Message" in str(e):
                self.logger.info("메시지가 삭제된 것으로 보입니다. 인터페이스를 재생성합니다.")
                self.lottery_interface_message = None
                await self.ensure_lottery_interface()
        except Exception as e:
            self.logger.error(f"복권 인터페이스 업데이트 중 예외 발생: {e}", exc_info=True)

    # Add command to manually refresh interface
    @app_commands.command(name="복권인터페이스새로고침", description="복권 인터페이스를 수동으로 새로고침 (관리자 전용)")
    async def refresh_lottery_interface(self, interaction: discord.Interaction):
        """Manually refresh the lottery interface"""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⛔ 관리자만 사용할 수 있습니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            await self.ensure_lottery_interface()
            await interaction.followup.send("✅ 복권 인터페이스가 새로고침되었습니다.", ephemeral=True)
        except Exception as e:
            self.logger.error(f"Manual interface refresh failed: {e}", exc_info=True)
            await interaction.followup.send("❌ 인터페이스 새로고침 중 오류가 발생했습니다.", ephemeral=True)

    # Rest of your existing methods (conduct_lottery_draw, lottery_automation_control, etc.)
    # ... [Include all other existing methods here]

    def get_lottery(self, guild_id: int) -> LotterySystem:
        """Get or create lottery system for guild"""
        if guild_id not in self.guild_lotteries:
            self.guild_lotteries[guild_id] = LotterySystem(guild_id)
        return self.guild_lotteries[guild_id]

    async def load_lottery_states(self):
        """Load lottery states from database"""
        try:
            if hasattr(self.bot, 'pool') and self.bot.pool:
                states = await self.bot.pool.fetch("SELECT * FROM lottery_state")
                for state in states:
                    lottery = LotterySystem(state['guild_id'])
                    lottery.pot_amount = state['pot_amount']
                    lottery.last_draw_time = state['last_draw_time']
                    lottery.winning_numbers = json.loads(state['winning_numbers']) if state['winning_numbers'] else []
                    lottery.last_prize_amount = state['last_prize_amount']
                    # Load entries if needed, etc.
                    self.guild_lotteries[state['guild_id']] = lottery
                    self.logger.info(f"Loaded lottery state for guild {state['guild_id']}")
        except Exception as e:
            self.logger.error(f"Error loading lottery states: {e}", exc_info=True)

    async def add_to_pot(self, guild_id: int, amount: int):
        """Add amount to lottery pot"""
        lottery = self.get_lottery(guild_id)
        lottery.pot_amount += amount
        # Update interface to reflect new pot amount
        await self.update_lottery_interface(guild_id)

    async def enter_lottery(self, user_id: int, guild_id: int, numbers: List[int]) -> tuple[bool, str]:
        """Enter user into lottery"""
        lottery = self.get_lottery(guild_id)
        if user_id in lottery.entries:
            return False, "이미 참가했습니다."

        valid, msg = self.validate_lottery_numbers(numbers)
        if not valid:
            return False, msg

        entry = LotteryEntry(user_id, numbers, datetime.now(timezone.utc))
        lottery.entries[user_id] = entry

        return True, f"참가 완료: {sorted(numbers)}"

    def validate_lottery_numbers(self, numbers: List[int]) -> tuple[bool, str]:
        """Validate lottery numbers"""
        if len(numbers) != 5:
            return False, "5개 번호를 선택해야 합니다."
        if len(set(numbers)) != 5:
            return False, "중복된 번호입니다."
        if any(n < 1 or n > 35 for n in numbers):
            return False, "번호는 1-35 사이여야 합니다."
        return True, "Valid"

    async def conduct_draw(self, guild_id: int) -> tuple[bool, str, dict]:
        """Conduct the lottery draw"""
        lottery = self.get_lottery(guild_id)
        if not lottery.entries:
            return False, "참가자가 없습니다.", {}

        # Generate random winning numbers
        winning_numbers = sorted(random.sample(range(1, 36), 5))

        # Calculate winners and prizes (simplified)
        results = {
            'winning_numbers': winning_numbers,
            'total_entries': len(lottery.entries),
            'total_awarded': 0,
            'remaining_pot': lottery.pot_amount,
            'winners': {}
        }

        # Reset entries after draw
        lottery.entries = {}
        lottery.winning_numbers = winning_numbers
        lottery.last_draw_time = datetime.now(timezone.utc)

        return True, "Draw successful", results

    async def debug_automation_status(self):
        """Debug method to check automation status"""
        self.logger.info("=== LOTTERY AUTOMATION DEBUG ===")
        self.logger.info(f"Task is_running(): {self.daily_lottery_draw.is_running()}")
        self.logger.info(f"Task current_loop: {self.daily_lottery_draw.current_loop}")
        self.logger.info(f"Task next_iteration: {self.daily_lottery_draw.next_iteration}")
        self.logger.info(f"Task failed(): {self.daily_lottery_draw.failed()}")
        if self.daily_lottery_draw.failed():
            self.logger.error(f"Task exception: {self.daily_lottery_draw.exception()}")
        self.logger.info("=== END DEBUG ===")

    @app_commands.command(name="복권디버그", description="복권 자동화 디버그 정보 (관리자 전용)")
    async def debug_lottery_automation(self, interaction: discord.Interaction):
        """Debug lottery automation status"""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⛔ 관리자만 사용할 수 있습니다.", ephemeral=True)
            return

        await self.debug_automation_status()

        embed = discord.Embed(
            title="🔧 복권 자동화 디버그 정보",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc)
        )

        embed.add_field(
            name="Task Status",
            value=f"Running: {self.daily_lottery_draw.is_running()}\nFailed: {self.daily_lottery_draw.failed()}",
            inline=True
        )

        if self.daily_lottery_draw.next_iteration:
            embed.add_field(
                name="Next Iteration",
                value=f"<t:{int(self.daily_lottery_draw.next_iteration.timestamp())}:F>",
                inline=True
            )

        embed.add_field(
            name="Current Loop",
            value=f"{self.daily_lottery_draw.current_loop}",
            inline=True
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="복권강제시작", description="복권 자동화 강제 시작 (관리자 전용)")
    async def force_start_lottery_automation(self, interaction: discord.Interaction):
        """Force start lottery automation with debugging"""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⛔ 관리자만 사용할 수 있습니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            # Cancel existing task if it's running but maybe stuck
            if self.daily_lottery_draw.is_running():
                self.logger.info("Cancelling existing lottery task...")
                self.daily_lottery_draw.cancel()
                await asyncio.sleep(1)  # Wait a moment for cleanup

            # Force restart the task
            self.logger.info("Force starting lottery automation...")
            self.daily_lottery_draw.start()

            await asyncio.sleep(2)  # Wait for startup

            # Check status
            is_running = self.daily_lottery_draw.is_running()

            if is_running:
                embed = discord.Embed(
                    title="✅ 자동화 강제 시작 성공",
                    description="복권 자동화가 성공적으로 시작되었습니다.",
                    color=discord.Color.green()
                )

                # Update the interface to show the new status
                await self.update_lottery_interface(interaction.guild.id)

            else:
                embed = discord.Embed(
                    title="❌ 자동화 시작 실패",
                    description="자동화 시작에 실패했습니다. 로그를 확인해주세요.",
                    color=discord.Color.red()
                )

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            self.logger.error(f"Force start failed: {e}", exc_info=True)
            await interaction.followup.send(f"강제 시작 중 오류: {e}", ephemeral=True)

# Include your existing Modal and View classes here
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
                    title="❌ 복권 참가 실패",
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

    # Add the remaining app_commands that were in your original code
    @app_commands.command(name="복권자동화설정", description="자동 복권 시스템 설정 (관리자 전용)")
    @app_commands.describe(action="start 또는 stop")
    async def lottery_automation_control(self, interaction: discord.Interaction, action: str):
        """Control the automated lottery system"""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⛔ 관리자만 사용할 수 있습니다.", ephemeral=True)
            return

        action = action.lower()

        if action == "start":
            if not self.daily_lottery_draw.is_running():
                self.daily_lottery_draw.start()
                embed = discord.Embed(
                    title="✅ 자동 복권 시스템 시작",
                    description="6시간마다 자동으로 복권 추첨이 진행됩니다.",
                    color=discord.Color.green()
                )
            else:
                embed = discord.Embed(
                    title="ℹ️ 자동 복권 시스템",
                    description="이미 자동 복권 시스템이 실행 중입니다.",
                    color=discord.Color.blue()
                )

        elif action == "stop":
            if self.daily_lottery_draw.is_running():
                self.daily_lottery_draw.cancel()
                embed = discord.Embed(
                    title="⏹️ 자동 복권 시스템 중지",
                    description="자동 복권 추첨이 중지되었습니다. 수동으로만 추첨 가능합니다.",
                    color=discord.Color.orange()
                )
            else:
                embed = discord.Embed(
                    title="ℹ️ 자동 복권 시스템",
                    description="자동 복권 시스템이 이미 중지되어 있습니다.",
                    color=discord.Color.blue()
                )

        else:
            embed = discord.Embed(
                title="❌ 잘못된 명령",
                description="'start' 또는 'stop'을 입력해주세요.",
                color=discord.Color.red()
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="복권자동화상태", description="자동 복권 시스템 상태 확인")
    async def lottery_automation_status(self, interaction: discord.Interaction):
        """Check automated lottery system status"""
        embed = discord.Embed(
            title="🤖 자동 복권 시스템 상태",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc)
        )

        if self.daily_lottery_draw.is_running():
            # Calculate next run time in EST/EDT
            est = pytz.timezone('US/Eastern')
            now_est = datetime.now(est)
            draw_times_est = [time(hour=0, minute=0), time(hour=6, minute=0), time(hour=12, minute=0),
                              time(hour=18, minute=0)]

            next_draw_time_utc = None
            for draw_time in draw_times_est:
                candidate_time = now_est.replace(hour=draw_time.hour, minute=draw_time.minute, second=0, microsecond=0)
                if candidate_time > now_est:
                    next_draw_time_utc = candidate_time
                    break

            # If no draw time is left for today, it's tomorrow's first draw (midnight Eastern)
            if next_draw_time_utc is None:
                next_draw_time_utc = now_est.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)

            embed.add_field(name="📊 상태", value="🟢 실행 중", inline=True)
            embed.add_field(name="⏰ 다음 추첨", value=f"<t:{int(next_draw_time_utc.timestamp())}:R>", inline=True)
            embed.add_field(name="🕐 추첨 시간", value="6시간마다 (EST)", inline=True)
        else:
            embed.add_field(name="📊 상태", value="🔴 중지됨", inline=True)
            embed.add_field(name="⏰ 다음 추첨", value="수동 추첨만 가능", inline=True)

        embed.add_field(
            name="🔧 제어 명령어",
            value="• `/복권자동화설정 start` - 시작\n• `/복권자동화설정 stop` - 중지",
            inline=False
        )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="복권추첨", description="복권 추첨을 실시합니다 (관리자 전용)")
    async def conduct_lottery_draw(self, interaction: discord.Interaction):
        """Conduct lottery draw (admin only)"""
        # Check admin permissions
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⛔ 관리자만 사용할 수 있습니다.", ephemeral=True)
            return

        await interaction.response.defer()

        success, message, results = await self.conduct_draw(interaction.guild.id)

        if not success:
            embed = discord.Embed(title="⛔ 추첨 실패", description=message, color=discord.Color.red())
            await interaction.followup.send(embed=embed)
            # Still repost interface even if draw failed (if no participants, etc.)
            await self.repost_lottery_interface(interaction.guild.id)
            return

        # Create results embed
        embed = discord.Embed(
            title="🎊 복권 추첨 결과! (수동 추첨)",
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

        # Send the draw results first
        await interaction.followup.send(embed=embed)

        # Always repost the lottery interface as the latest message
        await self.repost_lottery_interface(interaction.guild.id)


# Function to be called from casino games to add fees to lottery pot
async def add_casino_fee_to_lottery(bot, guild_id: int, fee_amount: int):
    """Add casino game fees to lottery pot"""
    lottery_cog = bot.get_cog('LotteryCog')
    if lottery_cog:
        await lottery_cog.add_to_pot(guild_id, fee_amount)


async def setup(bot):
    await bot.add_cog(LotteryCog(bot))