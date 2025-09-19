import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timezone, timedelta
import pytz

# Make sure to have these utility files or adjust the imports
from utils.logger import get_logger
from utils import config


class LoanRequestModal(discord.ui.Modal, title="대출 신청"):
    """Modal for users to request loans"""

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

        self.amount = discord.ui.TextInput(
            label="대출 금액",
            placeholder="신청할 대출 금액을 입력하세요 (예: 10000)",
            min_length=1,
            max_length=10,
        )
        self.add_item(self.amount)

        self.interest = discord.ui.TextInput(
            label="희망 이자율 (%)",
            placeholder="희망하는 이자율을 입력하세요 (예: 5.5)",
            min_length=1,
            max_length=5,
        )
        self.add_item(self.interest)

        self.days_due = discord.ui.TextInput(
            label="상환 기간 (일)",
            placeholder="상환 기간을 일 단위로 입력하세요 (예: 30)",
            min_length=1,
            max_length=3,
        )
        self.add_item(self.days_due)

        self.reason = discord.ui.TextInput(
            label="대출 사유",
            placeholder="대출이 필요한 이유를 간단히 설명해주세요",
            style=discord.TextStyle.paragraph,
            min_length=10,
            max_length=500,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            amount = int(self.amount.value.strip())
            interest_rate = float(self.interest.value.strip())
            days = int(self.days_due.value.strip())

            if amount <= 0 or interest_rate < 0 or days <= 0:
                return await interaction.followup.send("❌ 유효하지 않은 입력값입니다.", ephemeral=True)

            # Check if user already has an active loan
            existing_loan_query = "SELECT loan_id FROM user_loans WHERE user_id = $1 AND guild_id = $2 AND status IN ('active', 'defaulted')"
            existing_loan = await self.cog.bot.pool.fetchrow(existing_loan_query, interaction.user.id,
                                                             interaction.guild.id)

            if existing_loan:
                return await interaction.followup.send("❌ 이미 활성 상태의 대출이 있어 새로운 대출을 신청할 수 없습니다.", ephemeral=True)

            # Check for pending requests
            pending_query = "SELECT request_id FROM loan_requests WHERE user_id = $1 AND guild_id = $2 AND status = 'pending'"
            pending_request = await self.cog.bot.pool.fetchrow(pending_query, interaction.user.id, interaction.guild.id)

            if pending_request:
                return await interaction.followup.send("❌ 이미 검토 중인 대출 신청이 있습니다.", ephemeral=True)

            # Create loan request
            request_query = """
                INSERT INTO loan_requests (user_id, guild_id, amount, interest_rate, days_due, reason, status)
                VALUES ($1, $2, $3, $4, $5, $6, 'pending')
                RETURNING request_id
            """
            request_record = await self.cog.bot.pool.fetchrow(
                request_query, interaction.user.id, interaction.guild.id,
                amount, interest_rate, days, self.reason.value
            )

            # Send to admin review channel
            await self.cog.send_admin_review(request_record['request_id'], interaction.user, amount, interest_rate,
                                             days, self.reason.value)

            await interaction.followup.send("✅ 대출 신청이 성공적으로 제출되었습니다. 관리자가 검토 후 연락드리겠습니다.", ephemeral=True)

        except ValueError:
            await interaction.followup.send("❌ 숫자 형식이 올바르지 않습니다.", ephemeral=True)
        except Exception as e:
            self.cog.logger.error(f"대출 신청 처리 중 오류: {e}")
            await interaction.followup.send("❌ 대출 신청 처리 중 오류가 발생했습니다.", ephemeral=True)


class LoanRequestView(discord.ui.View):
    """Persistent view for loan requests"""

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="대출 신청",
        style=discord.ButtonStyle.primary,
        emoji="💰",
        custom_id="loan_request_button"
    )
    async def request_loan(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = LoanRequestModal(self.cog)
        await interaction.response.send_modal(modal)


class AdminReviewView(discord.ui.View):
    """Persistent view for admin loan review"""

    def __init__(self, cog, request_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.request_id = request_id

    @discord.ui.button(
        label="승인",
        style=discord.ButtonStyle.success,
        emoji="✅"
    )
    async def approve_loan(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog.has_admin_permissions(interaction.user):
            return await interaction.response.send_message("❌ 권한이 없습니다.", ephemeral=True)

        await self.cog.handle_loan_approval(interaction, self.request_id)

    @discord.ui.button(
        label="역제안",
        style=discord.ButtonStyle.secondary,
        emoji="📄"
    )
    async def counter_offer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog.has_admin_permissions(interaction.user):
            return await interaction.response.send_message("❌ 권한이 없습니다.", ephemeral=True)

        await self.cog.handle_counter_offer(interaction, self.request_id)

    @discord.ui.button(
        label="거부",
        style=discord.ButtonStyle.danger,
        emoji="❌"
    )
    async def deny_loan(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog.has_admin_permissions(interaction.user):
            return await interaction.response.send_message("❌ 권한이 없습니다.", ephemeral=True)

        await self.cog.handle_loan_denial(interaction, self.request_id)


class LoanChannelView(discord.ui.View):
    """Persistent view for loan management in individual channels"""

    def __init__(self, cog, loan_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.loan_id = loan_id

    @discord.ui.button(
        label="대출 상환",
        style=discord.ButtonStyle.primary,
        emoji="💳"
    )
    async def repay_loan(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = RepaymentModal(self.cog, self.loan_id)
        await interaction.response.send_modal(modal)


class RepaymentModal(discord.ui.Modal, title="대출 상환"):
    """Modal for loan repayment"""

    def __init__(self, cog, loan_id: int):
        super().__init__()
        self.cog = cog
        self.loan_id = loan_id

        self.amount = discord.ui.TextInput(
            label="상환 금액",
            placeholder="상환할 금액을 입력하세요",
            min_length=1,
            max_length=10,
        )
        self.add_item(self.amount)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            amount = int(self.amount.value.strip())
            if amount <= 0:
                return await interaction.followup.send("❌ 상환 금액은 0보다 커야 합니다.", ephemeral=True)

            await self.cog.process_repayment(interaction, self.loan_id, amount)

        except ValueError:
            await interaction.followup.send("❌ 유효한 숫자를 입력해주세요.", ephemeral=True)


class CounterOfferModal(discord.ui.Modal, title="역제안"):
    """Modal for counter offers"""

    def __init__(self, cog, request_id: int):
        super().__init__()
        self.cog = cog
        self.request_id = request_id

        self.amount = discord.ui.TextInput(
            label="대출 금액",
            placeholder="제안할 대출 금액",
            min_length=1,
            max_length=10,
        )
        self.add_item(self.amount)

        self.interest = discord.ui.TextInput(
            label="이자율 (%)",
            placeholder="제안할 이자율",
            min_length=1,
            max_length=5,
        )
        self.add_item(self.interest)

        self.days_due = discord.ui.TextInput(
            label="상환 기간 (일)",
            placeholder="제안할 상환 기간",
            min_length=1,
            max_length=3,
        )
        self.add_item(self.days_due)

        self.note = discord.ui.TextInput(
            label="추가 메모",
            placeholder="역제안 사유나 추가 설명",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=500,
        )
        self.add_item(self.note)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            amount = int(self.amount.value.strip())
            interest_rate = float(self.interest.value.strip())
            days = int(self.days_due.value.strip())

            await self.cog.create_negotiation_channel(
                interaction, self.request_id, amount, interest_rate, days, self.note.value
            )

        except ValueError:
            await interaction.followup.send("❌ 숫자 형식이 올바르지 않습니다.", ephemeral=True)


class FinalizeNegotiationModal(discord.ui.Modal, title="최종 대출 조건 확정"):
    """Modal for finalizing negotiated loan terms"""

    def __init__(self, cog, request_id: int):
        super().__init__()
        self.cog = cog
        self.request_id = request_id

        self.amount = discord.ui.TextInput(
            label="최종 대출 금액",
            placeholder="협상으로 확정된 대출 금액",
            min_length=1,
            max_length=10,
        )
        self.add_item(self.amount)

        self.interest = discord.ui.TextInput(
            label="최종 이자율 (%)",
            placeholder="협상으로 확정된 이자율",
            min_length=1,
            max_length=5,
        )
        self.add_item(self.interest)

        self.days_due = discord.ui.TextInput(
            label="최종 상환 기간 (일)",
            placeholder="협상으로 확정된 상환 기간",
            min_length=1,
            max_length=3,
        )
        self.add_item(self.days_due)

        self.summary = discord.ui.TextInput(
            label="협상 결과 요약",
            placeholder="협상 과정과 최종 합의 내용 요약",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=500,
        )
        self.add_item(self.summary)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            amount = int(self.amount.value.strip())
            interest_rate = float(self.interest.value.strip())
            days = int(self.days_due.value.strip())

            if amount <= 0 or interest_rate < 0 or days <= 0:
                return await interaction.followup.send("❌ 유효하지 않은 입력값입니다.", ephemeral=True)

            await self.cog.finalize_negotiated_loan(
                interaction, self.request_id, amount, interest_rate, days, self.summary.value
            )

        except ValueError:
            await interaction.followup.send("❌ 숫자 형식이 올바르지 않습니다.", ephemeral=True)


class RevisedCounterOfferModal(discord.ui.Modal, title="수정 역제안"):
    """Modal for proposing revised terms during negotiation"""

    def __init__(self, cog, request_id: int):
        super().__init__()
        self.cog = cog
        self.request_id = request_id

        self.amount = discord.ui.TextInput(
            label="수정된 대출 금액",
            placeholder="새로 제안할 대출 금액",
            min_length=1,
            max_length=10,
        )
        self.add_item(self.amount)

        self.interest = discord.ui.TextInput(
            label="수정된 이자율 (%)",
            placeholder="새로 제안할 이자율",
            min_length=1,
            max_length=5,
        )
        self.add_item(self.interest)

        self.days_due = discord.ui.TextInput(
            label="수정된 상환 기간 (일)",
            placeholder="새로 제안할 상환 기간",
            min_length=1,
            max_length=3,
        )
        self.add_item(self.days_due)

        self.reasoning = discord.ui.TextInput(
            label="수정 사유",
            placeholder="조건 변경 이유나 추가 설명",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=500,
        )
        self.add_item(self.reasoning)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            amount = int(self.amount.value.strip())
            interest_rate = float(self.interest.value.strip())
            days = int(self.days_due.value.strip())

            if amount <= 0 or interest_rate < 0 or days <= 0:
                return await interaction.followup.send("❌ 유효하지 않은 입력값입니다.", ephemeral=True)

            await self.cog.post_revised_counter_offer(
                interaction, self.request_id, amount, interest_rate, days, self.reasoning.value
            )

        except ValueError:
            await interaction.followup.send("❌ 숫자 형식이 올바르지 않습니다.", ephemeral=True)


class NegotiationChannelView(discord.ui.View):
    """Persistent view for negotiation channels with finalize option"""

    def __init__(self, cog, request_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.request_id = request_id

    @discord.ui.button(
        label="수정 역제안",
        style=discord.ButtonStyle.secondary,
        emoji="📝"
    )
    async def revised_counter_offer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog.has_admin_permissions(interaction.user):
            return await interaction.response.send_message("❌ 권한이 없습니다.", ephemeral=True)

        modal = RevisedCounterOfferModal(self.cog, self.request_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="협상 완료 - 대출 승인",
        style=discord.ButtonStyle.success,
        emoji="✅"
    )
    async def finalize_negotiation(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog.has_admin_permissions(interaction.user):
            return await interaction.response.send_message("❌ 권한이 없습니다.", ephemeral=True)

        modal = FinalizeNegotiationModal(self.cog, self.request_id)
        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="협상 중단",
        style=discord.ButtonStyle.danger,
        emoji="❌"
    )
    async def cancel_negotiation(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog.has_admin_permissions(interaction.user):
            return await interaction.response.send_message("❌ 권한이 없습니다.", ephemeral=True)

        await self.cog.cancel_negotiation(interaction, self.request_id)


class LoanCog(commands.Cog):
    """Enhanced loan cog with request system"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = get_logger("대출 시스템")

        # Channel IDs
        self.LOAN_REQUEST_CHANNEL = 1418708163259007077
        self.ADMIN_REVIEW_CHANNEL = 1418709157594398912
        self.LOAN_CATEGORY = 1417712502220783716

        # Start the background task after the bot is ready
        self.bot.loop.create_task(self.wait_and_start_tasks())

    async def wait_and_start_tasks(self):
        """Wait for the bot to be ready before setting up tables and starting tasks."""
        print("Waiting for bot to be ready...")
        await self.bot.wait_until_ready()
        print("Bot is ready, setting up tables...")
        await self.setup_loan_tables()
        await self.setup_request_interface()
        if not self.check_overdue_loans.is_running():
            self.check_overdue_loans.start()
        self.logger.info("대출 시스템 Cog가 초기화되고 백그라운드 작업이 시작되었습니다.")

    async def setup_loan_tables(self):
        """Creates the necessary database tables for the loan system."""
        try:
            # Original loans table
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS user_loans (
                    loan_id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    guild_id BIGINT NOT NULL,
                    principal_amount BIGINT NOT NULL,
                    remaining_amount BIGINT NOT NULL,
                    interest_rate NUMERIC(5, 2) NOT NULL,
                    status VARCHAR(20) DEFAULT 'active',
                    due_date TIMESTAMPTZ NOT NULL,
                    issued_at TIMESTAMPTZ DEFAULT NOW(),
                    channel_id BIGINT
                );
            """)

            # New loan requests table
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS loan_requests (
                    request_id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    guild_id BIGINT NOT NULL,
                    amount BIGINT NOT NULL,
                    interest_rate NUMERIC(5, 2) NOT NULL,
                    days_due INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    status VARCHAR(20) DEFAULT 'pending',
                    requested_at TIMESTAMPTZ DEFAULT NOW(),
                    channel_id BIGINT
                );
            """)

            self.logger.info("✅ 대출 데이터베이스 테이블이 준비되었습니다.")
        except Exception as e:
            self.logger.error(f"❌ 대출 테이블 설정 실패: {e}")

    async def setup_request_interface(self):
        """Set up the loan request interface"""
        try:
            channel = self.bot.get_channel(self.LOAN_REQUEST_CHANNEL)
            if not channel:
                self.logger.error(f"대출 신청 채널을 찾을 수 없습니다: {self.LOAN_REQUEST_CHANNEL}")
                return

            # Check if interface already exists
            async for message in channel.history(limit=10):
                if message.author == self.bot.user and message.embeds:
                    for embed in message.embeds:
                        if "대출 신청" in embed.title:
                            # Add the view to existing message
                            view = LoanRequestView(self)
                            self.bot.add_view(view, message_id=message.id)
                            self.logger.info("기존 대출 신청 인터페이스에 뷰를 연결했습니다.")
                            return

            # Create new interface
            embed = discord.Embed(
                title="💰 대출 신청 시스템",
                description="아래 버튼을 클릭하여 대출을 신청하실 수 있습니다.\n\n"
                            "**신청 전 안내사항:**\n"
                            "• 한 번에 하나의 대출만 가능합니다\n"
                            "• 모든 대출은 관리자 승인이 필요합니다\n"
                            "• 연체 시 추가 대출이 제한될 수 있습니다\n"
                            "• 상환은 언제든지 가능합니다",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_footer(text="신중한 대출 이용 부탁드립니다.")

            view = LoanRequestView(self)
            message = await channel.send(embed=embed, view=view)
            self.logger.info(f"대출 신청 인터페이스가 생성되었습니다: {message.id}")

        except Exception as e:
            self.logger.error(f"대출 신청 인터페이스 설정 실패: {e}")

    def has_admin_permissions(self, member: discord.Member) -> bool:
        """Check if a member has admin permissions for the bot."""
        if member.guild_permissions.administrator:
            return True

        try:
            admin_role_id = config.get_role_id(member.guild.id, 'admin_role')
            if admin_role_id and discord.utils.get(member.roles, id=admin_role_id):
                return True

            staff_role_id = config.get_role_id(member.guild.id, 'staff_role')
            if staff_role_id and discord.utils.get(member.roles, id=staff_role_id):
                return True
        except Exception as e:
            self.logger.warning(f"Error checking role permissions: {e}")

        return False

    async def send_admin_review(self, request_id: int, user: discord.Member, amount: int, interest_rate: float,
                                days: int, reason: str):
        """Send loan request to admin review channel"""
        try:
            channel = self.bot.get_channel(self.ADMIN_REVIEW_CHANNEL)
            if not channel:
                self.logger.error(f"관리자 검토 채널을 찾을 수 없습니다: {self.ADMIN_REVIEW_CHANNEL}")
                return

            total_repayment = amount + int(amount * (interest_rate / 100))

            embed = discord.Embed(
                title="📋 새로운 대출 신청",
                description=f"{user.mention}님의 대출 신청이 접수되었습니다.",
                color=discord.Color.orange(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="신청자", value=f"{user.display_name} ({user.id})", inline=True)
            embed.add_field(name="신청 금액", value=f"{amount:,} 코인", inline=True)
            embed.add_field(name="희망 이자율", value=f"{interest_rate}%", inline=True)
            embed.add_field(name="상환 기간", value=f"{days}일", inline=True)
            embed.add_field(name="총 상환액", value=f"{total_repayment:,} 코인", inline=True)
            embed.add_field(name="신청 ID", value=f"{request_id}", inline=True)
            embed.add_field(name="신청 사유", value=reason, inline=False)
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.set_footer(text="아래 버튼으로 대출을 승인, 역제안, 또는 거부할 수 있습니다.")

            view = AdminReviewView(self, request_id)
            await channel.send(embed=embed, view=view)

        except Exception as e:
            self.logger.error(f"관리자 검토 메시지 전송 실패: {e}")

    async def handle_loan_approval(self, interaction: discord.Interaction, request_id: int):
        """Handle loan approval"""
        await interaction.response.defer(ephemeral=True)

        try:
            # Get request details
            request_query = "SELECT * FROM loan_requests WHERE request_id = $1 AND status = 'pending'"
            request = await self.bot.pool.fetchrow(request_query, request_id)

            if not request:
                return await interaction.followup.send("❌ 유효하지 않은 대출 신청입니다.", ephemeral=True)

            user = self.bot.get_user(request['user_id'])
            if not user:
                return await interaction.followup.send("❌ 사용자를 찾을 수 없습니다.", ephemeral=True)

            guild_member = interaction.guild.get_member(request['user_id'])
            if not guild_member:
                return await interaction.followup.send("❌ 서버에서 사용자를 찾을 수 없습니다.", ephemeral=True)

            # Get coins cog
            coins_cog = self.bot.get_cog('CoinsCog')
            if not coins_cog:
                return await interaction.followup.send("❌ 코인 시스템을 찾을 수 없습니다.", ephemeral=True)

            # Create loan channel first
            channel = await self.create_loan_channel(interaction.guild, guild_member, request['amount'],
                                                     request['interest_rate'], request['days_due'])
            if not channel:
                return await interaction.followup.send("❌ 대출 채널 생성에 실패했습니다.", ephemeral=True)

            # Calculate loan details
            now_utc = datetime.now(timezone.utc)
            due_date = now_utc + timedelta(days=request['days_due'])
            total_repayment = request['amount'] + int(request['amount'] * (request['interest_rate'] / 100))

            # Create loan record
            loan_query = """
                INSERT INTO user_loans (user_id, guild_id, principal_amount, remaining_amount, interest_rate, due_date, status, channel_id)
                VALUES ($1, $2, $3, $4, $5, $6, 'active', $7)
                RETURNING loan_id
            """
            loan_record = await self.bot.pool.fetchrow(
                loan_query, request['user_id'], request['guild_id'],
                request['amount'], total_repayment, request['interest_rate'],
                due_date, channel.id
            )

            # Give coins to user
            success = await coins_cog.add_coins(
                request['user_id'], request['guild_id'], request['amount'],
                "loan_issued", f"Loan approved by {interaction.user.display_name}"
            )

            if not success:
                # Rollback
                await self.bot.pool.execute("DELETE FROM user_loans WHERE loan_id = $1", loan_record['loan_id'])
                try:
                    await channel.delete()
                except:
                    pass
                return await interaction.followup.send("❌ 코인 지급에 실패했습니다.", ephemeral=True)

            # Update request status
            await self.bot.pool.execute(
                "UPDATE loan_requests SET status = 'approved', channel_id = $1 WHERE request_id = $2",
                channel.id, request_id
            )

            # Update loan channel with loan info
            await self.update_loan_channel(channel, loan_record['loan_id'])

            # Update original message
            try:
                embed = interaction.message.embeds[0]
                embed.color = discord.Color.green()
                embed.title = "✅ 대출 승인됨"
                embed.add_field(name="처리자", value=interaction.user.display_name, inline=True)
                embed.add_field(name="대출 채널", value=channel.mention, inline=True)

                await interaction.message.edit(embed=embed, view=None)
            except Exception as e:
                self.logger.warning(f"원본 메시지 업데이트 실패: {e}")

            await interaction.followup.send(f"✅ 대출이 승인되었습니다. 채널: {channel.mention}", ephemeral=True)

            # Send DM to user
            try:
                dm_embed = discord.Embed(
                    title="✅ 대출 승인",
                    description=f"대출 신청이 승인되었습니다!",
                    color=discord.Color.green(),
                    timestamp=datetime.now(timezone.utc)
                )
                dm_embed.add_field(name="대출 금액", value=f"{request['amount']:,} 코인", inline=True)
                dm_embed.add_field(name="총 상환액", value=f"{total_repayment:,} 코인", inline=True)
                dm_embed.add_field(name="전용 채널", value=channel.mention, inline=False)

                await user.send(embed=dm_embed)
            except:
                pass

        except Exception as e:
            self.logger.error(f"대출 승인 처리 중 오류: {e}")
            await interaction.followup.send(f"❌ 승인 처리 중 오류가 발생했습니다: {e}", ephemeral=True)

    async def handle_counter_offer(self, interaction: discord.Interaction, request_id: int):
        """Handle counter offer"""
        modal = CounterOfferModal(self, request_id)
        await interaction.response.send_modal(modal)

    async def handle_loan_denial(self, interaction: discord.Interaction, request_id: int):
        """Handle loan denial"""
        await interaction.response.defer(ephemeral=True)

        try:
            # Get request details
            request_query = "SELECT user_id FROM loan_requests WHERE request_id = $1 AND status = 'pending'"
            request = await self.bot.pool.fetchrow(request_query, request_id)

            if not request:
                return await interaction.followup.send("❌ 유효하지 않은 대출 신청입니다.", ephemeral=True)

            user = self.bot.get_user(request['user_id'])

            # Update request status
            await self.bot.pool.execute("UPDATE loan_requests SET status = 'denied' WHERE request_id = $1", request_id)

            # Update message
            try:
                embed = interaction.message.embeds[0]
                embed.color = discord.Color.red()
                embed.title = "❌ 대출 거부됨"
                embed.add_field(name="처리자", value=interaction.user.display_name, inline=True)

                await interaction.message.edit(embed=embed, view=None)
            except Exception as e:
                self.logger.warning(f"원본 메시지 업데이트 실패: {e}")

            await interaction.followup.send("✅ 대출 신청이 거부되었습니다.", ephemeral=True)

            # Send DM to user
            if user:
                try:
                    dm_embed = discord.Embed(
                        title="❌ 대출 신청 거부",
                        description="죄송합니다. 대출 신청이 거부되었습니다.",
                        color=discord.Color.red(),
                        timestamp=datetime.now(timezone.utc)
                    )
                    await user.send(embed=dm_embed)
                except:
                    pass

        except Exception as e:
            self.logger.error(f"대출 거부 처리 중 오류: {e}")
            await interaction.followup.send(f"❌ 거부 처리 중 오류가 발생했습니다: {e}", ephemeral=True)

    async def create_loan_channel(self, guild: discord.Guild, user: discord.Member, amount: int, interest_rate: float,
                                  days: int) -> discord.TextChannel:
        """Create a private loan channel with comprehensive error handling"""
        try:
            # Get category safely
            category = None
            if self.LOAN_CATEGORY:
                category = guild.get_channel(self.LOAN_CATEGORY)
                if category and not isinstance(category, discord.CategoryChannel):
                    category = None

            # Prepare overwrites
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True)
            }

            # Add admin roles safely
            try:
                admin_role_id = config.get_role_id(guild.id, 'admin_role')
                if admin_role_id:
                    admin_role = guild.get_role(admin_role_id)
                    if admin_role:
                        overwrites[admin_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

                staff_role_id = config.get_role_id(guild.id, 'staff_role')
                if staff_role_id:
                    staff_role = guild.get_role(staff_role_id)
                    if staff_role:
                        overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            except Exception as e:
                self.logger.warning(f"관리자 역할 추가 중 오류: {e}")

            # Create channel
            channel_name = f"loan-{user.display_name}-{amount}".lower().replace(" ", "-")

            channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"Private loan channel for {user.display_name}",
                reason=f"Loan channel created for {user.display_name}"
            )

            self.logger.info(f"대출 채널 생성 성공: {channel.name} ({channel.id})")
            return channel

        except Exception as e:
            self.logger.error(f"대출 채널 생성 실패: {e}")
            return None

    async def update_loan_channel(self, channel: discord.TextChannel, loan_id: int):
        """Update loan channel with current loan information"""
        try:
            # Get loan details
            loan_query = "SELECT * FROM user_loans WHERE loan_id = $1"
            loan = await self.bot.pool.fetchrow(loan_query, loan_id)

            if not loan:
                return

            user = self.bot.get_user(loan['user_id'])
            if not user:
                return

            # Create embed
            status_color = discord.Color.green() if loan['status'] == 'active' else discord.Color.red()
            status_emoji = "🟢 활성" if loan['status'] == 'active' else "🔴 연체" if loan['status'] == 'defaulted' else "✅ 완료"

            embed = discord.Embed(
                title=f"💰 {user.display_name}님의 대출 정보",
                color=status_color,
                timestamp=datetime.now(timezone.utc)
            )

            embed.add_field(name="상태", value=status_emoji, inline=True)
            embed.add_field(name="원금", value=f"{loan['principal_amount']:,} 코인", inline=True)
            embed.add_field(name="남은 상환액", value=f"{loan['remaining_amount']:,} 코인", inline=True)
            embed.add_field(name="이자율", value=f"{loan['interest_rate']}%", inline=True)

            due_date = loan['due_date']
            if due_date.tzinfo is None:
                due_date = due_date.replace(tzinfo=timezone.utc)

            embed.add_field(name="상환 기한", value=f"<t:{int(due_date.timestamp())}:R>", inline=True)
            embed.add_field(name="발행일", value=f"<t:{int(loan['issued_at'].timestamp())}:f>", inline=True)
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.set_footer(text=f"대출 ID: {loan['loan_id']}")

            # Create view with repayment button
            view = LoanChannelView(self, loan_id) if loan['status'] == 'active' else None

            # Clear channel and post updated info
            await channel.purge(limit=100)
            await channel.send(embed=embed, view=view)

        except Exception as e:
            self.logger.error(f"대출 채널 업데이트 실패: {e}")

    async def create_negotiation_channel(self, interaction: discord.Interaction, request_id: int,
                                         counter_amount: int, counter_interest: float, counter_days: int, note: str):
        """Create negotiation channel with comprehensive error handling"""
        try:
            # Get request and validate
            request_query = "SELECT * FROM loan_requests WHERE request_id = $1 AND status = 'pending'"
            request = await self.bot.pool.fetchrow(request_query, request_id)

            if not request:
                return await interaction.followup.send("❌ 유효하지 않은 대출 신청입니다.", ephemeral=True)

            user = self.bot.get_user(request['user_id'])
            if not user:
                return await interaction.followup.send("❌ 사용자를 찾을 수 없습니다.", ephemeral=True)

            guild_member = interaction.guild.get_member(request['user_id'])
            if not guild_member:
                return await interaction.followup.send("❌ 서버에서 사용자를 찾을 수 없습니다.", ephemeral=True)

            guild = interaction.guild

            # Get category safely
            category = None
            if self.LOAN_CATEGORY:
                category = guild.get_channel(self.LOAN_CATEGORY)
                if category and not isinstance(category, discord.CategoryChannel):
                    category = None

            # Prepare overwrites
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                guild_member: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True)
            }

            # Add admin roles safely
            try:
                admin_role_id = config.get_role_id(guild.id, 'admin_role')
                if admin_role_id:
                    admin_role = guild.get_role(admin_role_id)
                    if admin_role:
                        overwrites[admin_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

                staff_role_id = config.get_role_id(guild.id, 'staff_role')
                if staff_role_id:
                    staff_role = guild.get_role(staff_role_id)
                    if staff_role:
                        overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            except Exception as e:
                self.logger.warning(f"관리자 역할 추가 중 오류: {e}")

            # Create negotiation channel
            channel_name = f"negotiation-{guild_member.display_name}-{request_id}".lower().replace(" ", "-")

            channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"Loan negotiation for {guild_member.display_name}",
                reason=f"Counter offer negotiation created by {interaction.user.display_name}"
            )

            # Update database
            await self.bot.pool.execute(
                "UPDATE loan_requests SET status = 'negotiating', channel_id = $1 WHERE request_id = $2",
                channel.id, request_id
            )

            # Send embed to channel
            embed = discord.Embed(
                title="📄 대출 역제안",
                description=f"{guild_member.mention}님의 대출 신청에 대한 관리자 역제안입니다.",
                color=discord.Color.orange(),
                timestamp=datetime.now(timezone.utc)
            )

            embed.add_field(
                name="📋 원래 신청 조건",
                value=f"**금액:** {request['amount']:,} 코인\n**이자율:** {request['interest_rate']}%\n**기간:** {request['days_due']}일",
                inline=True
            )

            total_counter = counter_amount + int(counter_amount * (counter_interest / 100))
            embed.add_field(
                name="💡 역제안 조건",
                value=f"**금액:** {counter_amount:,} 코인\n**이자율:** {counter_interest}%\n**기간:** {counter_days}일\n**총 상환액:** {total_counter:,} 코인",
                inline=True
            )

            if note:
                embed.add_field(name="📝 관리자 메모", value=note, inline=False)

            embed.add_field(
                name="💬 협상 안내",
                value="이 채널에서 대출 조건에 대해 자유롭게 논의하실 수 있습니다.\n최종 합의 후 관리자가 대출을 승인하게 됩니다.",
                inline=False
            )

            embed.set_footer(text=f"제안자: {interaction.user.display_name}")

            # Add negotiation control buttons
            view = NegotiationChannelView(self, request_id)
            await channel.send(f"{guild_member.mention} 관리자들", embed=embed, view=view)

            # Update original message
            try:
                orig_embed = interaction.message.embeds[0]
                orig_embed.color = discord.Color.orange()
                orig_embed.title = "📄 역제안 진행 중"
                orig_embed.add_field(name="처리자", value=interaction.user.display_name, inline=True)
                orig_embed.add_field(name="협상 채널", value=channel.mention, inline=True)
                await interaction.message.edit(embed=orig_embed, view=None)
            except Exception as e:
                self.logger.warning(f"원본 메시지 업데이트 실패: {e}")

            await interaction.followup.send(f"✅ 역제안을 위한 협상 채널이 생성되었습니다: {channel.mention}", ephemeral=True)

            # Send DM to user
            try:
                dm_embed = discord.Embed(
                    title="📄 대출 역제안",
                    description=f"대출 신청에 대한 관리자 역제안이 있습니다.",
                    color=discord.Color.orange(),
                    timestamp=datetime.now(timezone.utc)
                )
                dm_embed.add_field(name="협상 채널", value=channel.mention, inline=False)
                await user.send(embed=dm_embed)
            except Exception as e:
                self.logger.warning(f"사용자 DM 전송 실패: {e}")

        except Exception as e:
            self.logger.error(f"협상 채널 생성 중 오류: {e}")
            try:
                await interaction.followup.send(f"❌ 협상 채널 생성 중 오류가 발생했습니다: {str(e)}", ephemeral=True)
            except:
                pass

    async def finalize_negotiated_loan(self, interaction: discord.Interaction, request_id: int,
                                       final_amount: int, final_interest: float, final_days: int, summary: str):
        """Finalize negotiated loan terms and approve the loan"""
        try:
            # Get request details
            request_query = "SELECT * FROM loan_requests WHERE request_id = $1 AND status = 'negotiating'"
            request = await self.bot.pool.fetchrow(request_query, request_id)

            if not request:
                return await interaction.followup.send("❌ 유효하지 않은 협상 중인 대출 신청입니다.", ephemeral=True)

            user = self.bot.get_user(request['user_id'])
            if not user:
                return await interaction.followup.send("❌ 사용자를 찾을 수 없습니다.", ephemeral=True)

            guild_member = interaction.guild.get_member(request['user_id'])
            if not guild_member:
                return await interaction.followup.send("❌ 서버에서 사용자를 찾을 수 없습니다.", ephemeral=True)

            # Get coins cog
            coins_cog = self.bot.get_cog('CoinsCog')
            if not coins_cog:
                return await interaction.followup.send("❌ 코인 시스템을 찾을 수 없습니다.", ephemeral=True)

            # Create loan channel
            loan_channel = await self.create_loan_channel(interaction.guild, guild_member, final_amount, final_interest,
                                                          final_days)
            if not loan_channel:
                return await interaction.followup.send("❌ 대출 채널 생성에 실패했습니다.", ephemeral=True)

            # Calculate loan details
            now_utc = datetime.now(timezone.utc)
            due_date = now_utc + timedelta(days=final_days)
            total_repayment = final_amount + int(final_amount * (final_interest / 100))

            # Create loan record
            loan_query = """
                INSERT INTO user_loans (user_id, guild_id, principal_amount, remaining_amount, interest_rate, due_date, status, channel_id)
                VALUES ($1, $2, $3, $4, $5, $6, 'active', $7)
                RETURNING loan_id
            """
            loan_record = await self.bot.pool.fetchrow(
                loan_query, request['user_id'], request['guild_id'],
                final_amount, total_repayment, final_interest, due_date, loan_channel.id
            )

            # Give coins to user
            success = await coins_cog.add_coins(
                request['user_id'], request['guild_id'], final_amount,
                "loan_issued", f"Negotiated loan approved by {interaction.user.display_name}"
            )

            if not success:
                # Rollback
                await self.bot.pool.execute("DELETE FROM user_loans WHERE loan_id = $1", loan_record['loan_id'])
                try:
                    await loan_channel.delete()
                except:
                    pass
                return await interaction.followup.send("❌ 코인 지급에 실패했습니다.", ephemeral=True)

            # Update request status with final terms
            await self.bot.pool.execute(
                """UPDATE loan_requests SET 
                   status = 'approved_negotiated', 
                   amount = $1, 
                   interest_rate = $2, 
                   days_due = $3 
                   WHERE request_id = $4""",
                final_amount, final_interest, final_days, request_id
            )

            # Update loan channel with loan info
            await self.update_loan_channel(loan_channel, loan_record['loan_id'])

            # Post completion message in negotiation channel
            completion_embed = discord.Embed(
                title="✅ 협상 완료 - 대출 승인됨",
                description=f"협상이 성공적으로 완료되어 대출이 승인되었습니다!",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )

            completion_embed.add_field(
                name="📋 최종 확정 조건",
                value=f"**대출 금액:** {final_amount:,} 코인\n**이자율:** {final_interest}%\n**상환 기간:** {final_days}일\n**총 상환액:** {total_repayment:,} 코인",
                inline=False
            )

            if summary:
                completion_embed.add_field(name="📝 협상 요약", value=summary, inline=False)

            completion_embed.add_field(name="🏦 대출 채널", value=loan_channel.mention, inline=False)
            completion_embed.add_field(name="👤 승인자", value=interaction.user.display_name, inline=True)
            completion_embed.add_field(name="💰 코인 지급됨", value=f"{final_amount:,} 코인", inline=True)

            # Disable negotiation buttons
            for item in interaction.message.components:
                for component in item.children:
                    component.disabled = True

            await interaction.message.edit(view=None)
            await interaction.channel.send(embed=completion_embed)

            await interaction.followup.send(f"✅ 협상이 완료되어 대출이 승인되었습니다! 대출 채널: {loan_channel.mention}", ephemeral=True)

            # Send success DM to user
            try:
                dm_embed = discord.Embed(
                    title="🎉 대출 승인 (협상 완료)",
                    description=f"협상을 통해 대출 신청이 승인되었습니다!",
                    color=discord.Color.green(),
                    timestamp=datetime.now(timezone.utc)
                )
                dm_embed.add_field(name="최종 대출 금액", value=f"{final_amount:,} 코인", inline=True)
                dm_embed.add_field(name="총 상환액", value=f"{total_repayment:,} 코인", inline=True)
                dm_embed.add_field(name="대출 관리 채널", value=loan_channel.mention, inline=False)

                await user.send(embed=dm_embed)
            except:
                pass

            # Clean up negotiation channel after delay
            try:
                await interaction.channel.send("📋 이 협상 채널은 60초 후 자동으로 삭제됩니다.")
                import asyncio
                await asyncio.sleep(60)
                await interaction.channel.delete()
            except:
                pass

        except Exception as e:
            self.logger.error(f"협상 완료 처리 중 오류: {e}")
            await interaction.followup.send(f"❌ 협상 완료 처리 중 오류가 발생했습니다: {e}", ephemeral=True)

    async def cancel_negotiation(self, interaction: discord.Interaction, request_id: int):
        """Cancel the negotiation and mark request as denied"""
        await interaction.response.defer(ephemeral=True)

        try:
            # Get request details
            request_query = "SELECT user_id FROM loan_requests WHERE request_id = $1 AND status = 'negotiating'"
            request = await self.bot.pool.fetchrow(request_query, request_id)

            if not request:
                return await interaction.followup.send("❌ 유효하지 않은 협상 중인 대출 신청입니다.", ephemeral=True)

            user = self.bot.get_user(request['user_id'])

            # Update request status
            await self.bot.pool.execute(
                "UPDATE loan_requests SET status = 'denied_after_negotiation' WHERE request_id = $1", request_id)

            # Post cancellation message
            cancel_embed = discord.Embed(
                title="❌ 협상 중단됨",
                description=f"대출 신청에 대한 협상이 중단되었습니다.",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc)
            )
            cancel_embed.add_field(name="처리자", value=interaction.user.display_name, inline=True)
            cancel_embed.add_field(name="처리 시간", value=f"<t:{int(datetime.now(timezone.utc).timestamp())}:f>",
                                   inline=True)

            # Disable negotiation buttons
            for item in interaction.message.components:
                for component in item.children:
                    component.disabled = True

            await interaction.message.edit(view=None)
            await interaction.channel.send(embed=cancel_embed)

            await interaction.followup.send("✅ 협상이 중단되었습니다.", ephemeral=True)

            # Send notification DM to user
            if user:
                try:
                    dm_embed = discord.Embed(
                        title="❌ 대출 신청 협상 중단",
                        description="죄송합니다. 대출 신청에 대한 협상이 중단되었습니다.",
                        color=discord.Color.red(),
                        timestamp=datetime.now(timezone.utc)
                    )
                    await user.send(embed=dm_embed)
                except:
                    pass

            # Clean up negotiation channel after delay
            try:
                await interaction.channel.send("📋 이 협상 채널은 30초 후 자동으로 삭제됩니다.")
                import asyncio
                await asyncio.sleep(30)
                await interaction.channel.delete()
            except:
                pass

        except Exception as e:
            self.logger.error(f"협상 중단 처리 중 오류: {e}")
            await interaction.followup.send(f"❌ 협상 중단 처리 중 오류가 발생했습니다: {e}", ephemeral=True)

    async def post_revised_counter_offer(self, interaction: discord.Interaction, request_id: int,
                                         revised_amount: int, revised_interest: float, revised_days: int,
                                         reasoning: str):
        """Post a revised counter-offer in the negotiation channel"""
        try:
            # Get original request details
            request_query = "SELECT * FROM loan_requests WHERE request_id = $1"
            request = await self.bot.pool.fetchrow(request_query, request_id)

            if not request:
                return await interaction.followup.send("❌ 유효하지 않은 대출 신청입니다.", ephemeral=True)

            user = self.bot.get_user(request['user_id'])
            if not user:
                return await interaction.followup.send("❌ 사용자를 찾을 수 없습니다.", ephemeral=True)

            # Convert decimal values to float for calculations
            original_amount = int(request['amount'])
            original_interest = float(request['interest_rate'])
            original_days = int(request['days_due'])

            # Calculate totals
            original_total = original_amount + int(original_amount * (original_interest / 100))
            revised_total = revised_amount + int(revised_amount * (revised_interest / 100))

            # Create comparison embed
            comparison_embed = discord.Embed(
                title="📝 수정된 역제안",
                description=f"{interaction.user.display_name}님이 새로운 조건을 제안했습니다.",
                color=discord.Color.gold(),
                timestamp=datetime.now(timezone.utc)
            )

            # Original request terms
            comparison_embed.add_field(
                name="📋 원래 신청 조건",
                value=f"**금액:** {original_amount:,} 코인\n**이자율:** {original_interest}%\n**기간:** {original_days}일\n**총 상환액:** {original_total:,} 코인",
                inline=True
            )

            # New proposed terms
            comparison_embed.add_field(
                name="💡 수정 제안 조건",
                value=f"**금액:** {revised_amount:,} 코인\n**이자율:** {revised_interest}%\n**기간:** {revised_days}일\n**총 상환액:** {revised_total:,} 코인",
                inline=True
            )

            # Show changes
            amount_change = revised_amount - original_amount
            interest_change = revised_interest - original_interest
            days_change = revised_days - original_days
            total_change = revised_total - original_total

            change_symbols = {
                True: "📈 +",
                False: "📉 "
            }

            changes_text = f"""
            **금액 변화:** {change_symbols[amount_change >= 0]}{amount_change:+,} 코인
            **이자율 변화:** {change_symbols[interest_change >= 0]}{interest_change:+.1f}%
            **기간 변화:** {change_symbols[days_change >= 0]}{days_change:+} 일
            **총 상환액 변화:** {change_symbols[total_change >= 0]}{total_change:+,} 코인
            """

            comparison_embed.add_field(
                name="📊 변경 사항",
                value=changes_text,
                inline=False
            )

            if reasoning:
                comparison_embed.add_field(
                    name="💭 수정 사유",
                    value=reasoning,
                    inline=False
                )

            comparison_embed.add_field(
                name="❓ 다음 단계",
                value=f"{user.mention}님, 위 수정된 조건에 대해 어떻게 생각하시나요? 자유롭게 의견을 남겨주세요.\n\n관리자들은 추가 수정이나 최종 승인을 결정할 수 있습니다.",
                inline=False
            )

            comparison_embed.set_footer(text=f"제안자: {interaction.user.display_name}")

            # Post the revised offer
            await interaction.channel.send(f"🔄 **수정 제안 알림** {user.mention}", embed=comparison_embed)

            await interaction.followup.send("✅ 수정된 역제안이 협상 채널에 게시되었습니다.", ephemeral=True)

            # Send notification DM to user
            try:
                dm_embed = discord.Embed(
                    title="📝 대출 조건 수정 제안",
                    description=f"협상 중인 대출에 대해 관리자가 수정된 조건을 제안했습니다.",
                    color=discord.Color.gold(),
                    timestamp=datetime.now(timezone.utc)
                )
                dm_embed.add_field(
                    name="수정 제안 조건",
                    value=f"**금액:** {revised_amount:,} 코인\n**이자율:** {revised_interest}%\n**기간:** {revised_days}일",
                    inline=False
                )
                dm_embed.add_field(
                    name="협상 채널",
                    value=f"자세한 내용은 {interaction.channel.mention}에서 확인해주세요.",
                    inline=False
                )

                await user.send(embed=dm_embed)
            except Exception as e:
                self.logger.warning(f"수정 제안 DM 전송 실패: {e}")

        except Exception as e:
            self.logger.error(f"수정 역제안 게시 중 오류: {e}")
            await interaction.followup.send(f"❌ 수정 역제안 게시 중 오류가 발생했습니다: {e}", ephemeral=True)

    async def process_repayment(self, interaction: discord.Interaction, loan_id: int, amount: int):
        """Process loan repayment"""
        try:
            coins_cog = self.bot.get_cog('CoinsCog')
            if not coins_cog:
                return await interaction.followup.send("❌ 코인 시스템을 찾을 수 없습니다!", ephemeral=True)

            # Find the loan
            query = "SELECT * FROM user_loans WHERE loan_id = $1 AND status IN ('active', 'defaulted')"
            loan = await self.bot.pool.fetchrow(query, loan_id)
            if not loan:
                return await interaction.followup.send("❌ 유효한 대출을 찾을 수 없습니다.", ephemeral=True)

            if loan['user_id'] != interaction.user.id:
                return await interaction.followup.send("❌ 본인의 대출만 상환할 수 있습니다.", ephemeral=True)

            # Ensure they don't overpay
            payment_amount = min(amount, loan['remaining_amount'])

            # Check balance
            user_balance = await coins_cog.get_user_coins(interaction.user.id, interaction.guild.id)
            if user_balance < payment_amount:
                return await interaction.followup.send(
                    f"❌ 코인이 부족합니다. 필요: {payment_amount:,}, 보유: {user_balance:,}", ephemeral=True)

            # Process payment
            success = await coins_cog.remove_coins(
                interaction.user.id, interaction.guild.id, payment_amount,
                "loan_repayment", f"Payment for loan ID {loan['loan_id']}"
            )
            if not success:
                return await interaction.followup.send("❌ 상환 처리 중 오류가 발생했습니다.", ephemeral=True)

            new_remaining = loan['remaining_amount'] - payment_amount
            if new_remaining <= 0:
                # Loan fully paid
                await self.bot.pool.execute(
                    "UPDATE user_loans SET remaining_amount = 0, status = 'paid' WHERE loan_id = $1", loan_id)

                await interaction.followup.send(
                    f"🎉 **{payment_amount:,} 코인**을 상환하여 대출을 모두 갚았습니다! 축하합니다!", ephemeral=True)

                # Delete channel after a delay
                channel = self.bot.get_channel(loan['channel_id'])
                if channel:
                    final_embed = discord.Embed(
                        title="✅ 대출 완전 상환 완료!",
                        description=f"{interaction.user.mention}님이 대출을 모두 상환했습니다.\n\n이 채널은 30초 후 자동으로 삭제됩니다.",
                        color=discord.Color.green(),
                        timestamp=datetime.now(timezone.utc)
                    )
                    await channel.send(embed=final_embed)

                    import asyncio
                    await asyncio.sleep(30)
                    try:
                        await channel.delete()
                    except:
                        pass
            else:
                # Partial payment
                await self.bot.pool.execute("UPDATE user_loans SET remaining_amount = $1 WHERE loan_id = $2",
                                            new_remaining, loan_id)
                await interaction.followup.send(
                    f"✅ **{payment_amount:,} 코인**을 상환했습니다. 남은 금액: **{new_remaining:,} 코인**", ephemeral=True)

                # Update channel
                channel = self.bot.get_channel(loan['channel_id'])
                if channel:
                    await self.update_loan_channel(channel, loan_id)

        except Exception as e:
            self.logger.error(f"대출 상환 처리 중 오류: {e}")
            await interaction.followup.send(f"❌ 상환 처리 중 오류가 발생했습니다: {e}", ephemeral=True)

    @tasks.loop(hours=24)
    async def check_overdue_loans(self):
        """Daily check for loans that have passed their due date."""
        current_time = datetime.now(timezone.utc)
        self.logger.info("연체된 대출을 확인하는 중...")
        try:
            query = "SELECT loan_id, user_id, channel_id FROM user_loans WHERE status = 'active' AND due_date < $1"
            overdue_loans = await self.bot.pool.fetch(query, current_time)

            for loan in overdue_loans:
                update_query = "UPDATE user_loans SET status = 'defaulted' WHERE loan_id = $1"
                await self.bot.pool.execute(update_query, loan['loan_id'])
                self.logger.info(f"대출 ID {loan['loan_id']} (사용자: {loan['user_id']})가 'defaulted'로 변경되었습니다.")

                # Update loan channel if exists
                if loan['channel_id']:
                    channel = self.bot.get_channel(loan['channel_id'])
                    if channel:
                        await self.update_loan_channel(channel, loan['loan_id'])

        except Exception as e:
            self.logger.error(f"연체된 대출 확인 중 오류 발생: {e}")

    # Slash commands
    @app_commands.command(name="카테고리확인", description="카테고리 ID 확인 (관리자 전용)")
    async def verify_category(self, interaction: discord.Interaction):
        if not self.has_admin_permissions(interaction.user):
            return await interaction.response.send_message("❌ 권한이 없습니다.", ephemeral=True)

        guild = interaction.guild
        category = guild.get_channel(self.LOAN_CATEGORY)

        embed = discord.Embed(title="카테고리 확인 결과", color=discord.Color.blue())
        embed.add_field(name="설정된 카테고리 ID", value=f"`{self.LOAN_CATEGORY}`", inline=False)

        if category:
            embed.add_field(
                name="카테고리 정보",
                value=f"이름: {category.name}\n타입: {type(category).__name__}\n카테고리 여부: {isinstance(category, discord.CategoryChannel)}",
                inline=False
            )
            bot_perms = category.permissions_for(guild.me)
            embed.add_field(
                name="봇 권한",
                value=f"채널 관리: {bot_perms.manage_channels}\n메시지 전송: {bot_perms.send_messages}\n채널 보기: {bot_perms.view_channel}",
                inline=False
            )
        else:
            embed.add_field(name="오류", value="카테고리를 찾을 수 없습니다!", inline=False)

        # List all categories
        all_categories = [ch for ch in guild.channels if isinstance(ch, discord.CategoryChannel)]
        category_list = "\n".join([f"{cat.name} (`{cat.id}`)" for cat in all_categories[:10]])
        embed.add_field(
            name="서버의 모든 카테고리 (최대 10개)",
            value=category_list if category_list else "카테고리가 없습니다.",
            inline=False
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="대출발행", description="사용자에게 대출을 발행합니다. (관리자 전용)")
    @app_commands.describe(
        user="대출을 받을 사용자",
        amount="대출 원금",
        interest="이자율 (%)",
        days_due="상환 기한 (일)"
    )
    async def issue_loan(self, interaction: discord.Interaction, user: discord.Member, amount: int,
                         interest: float, days_due: int):
        if not self.has_admin_permissions(interaction.user):
            return await interaction.response.send_message("❌ 이 명령어를 사용할 권한이 없습니다.", ephemeral=True)

        if amount <= 0 or interest < 0 or days_due <= 0:
            return await interaction.response.send_message("❌ 유효하지 않은 입력값입니다. 모든 값은 0보다 커야 합니다.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        try:
            coins_cog = self.bot.get_cog('CoinsCog')
            if not coins_cog:
                return await interaction.followup.send("❌ 코인 시스템을 찾을 수 없습니다!", ephemeral=True)

            # Check if user already has an active or defaulted loan
            existing_loan_query = "SELECT loan_id FROM user_loans WHERE user_id = $1 AND guild_id = $2 AND status IN ('active', 'defaulted')"
            existing_loan = await self.bot.pool.fetchrow(existing_loan_query, user.id, interaction.guild_id)

            if existing_loan:
                return await interaction.followup.send(f"❌ {user.display_name}님은 이미 활성 상태의 대출이 있습니다!", ephemeral=True)

            # Create loan channel
            channel = await self.create_loan_channel(interaction.guild, user, amount, interest, days_due)
            if not channel:
                return await interaction.followup.send("❌ 대출 채널 생성에 실패했습니다.", ephemeral=True)

            # Calculate dates and amounts
            now_utc = datetime.now(timezone.utc)
            due_date = now_utc + timedelta(days=days_due)
            total_repayment = amount + int(amount * (interest / 100))

            # Insert loan record
            query = """
                INSERT INTO user_loans (user_id, guild_id, principal_amount, remaining_amount, interest_rate, due_date, status, channel_id)
                VALUES ($1, $2, $3, $4, $5, $6, 'active', $7)
                RETURNING loan_id
            """
            loan_record = await self.bot.pool.fetchrow(
                query, user.id, interaction.guild_id, amount, total_repayment, interest, due_date, channel.id
            )

            if not loan_record:
                await channel.delete()
                return await interaction.followup.send("❌ 대출 기록 생성에 실패했습니다.", ephemeral=True)

            # Add coins to user's balance
            success = await coins_cog.add_coins(user.id, interaction.guild_id, amount, "loan_issued",
                                                f"Loan issued by {interaction.user.display_name}")

            if not success:
                await self.bot.pool.execute("DELETE FROM user_loans WHERE loan_id = $1", loan_record['loan_id'])
                await channel.delete()
                return await interaction.followup.send("❌ 코인 지급에 실패했습니다. 대출이 취소되었습니다.", ephemeral=True)

            # Update loan channel
            await self.update_loan_channel(channel, loan_record['loan_id'])

            await interaction.followup.send(
                f"✅ {user.mention}님에게 {amount:,} 코인 대출을 발행했습니다. 채널: {channel.mention}")

            # Send DM to user
            try:
                embed = discord.Embed(
                    title=f"{interaction.guild.name} 대출 승인",
                    description=f"관리자에 의해 대출이 승인되었습니다.",
                    color=discord.Color.green(),
                    timestamp=now_utc
                )
                embed.add_field(name="대출 원금", value=f"{amount:,} 코인", inline=False)
                embed.add_field(name="총 상환액", value=f"{total_repayment:,} 코인 ({interest}% 이자 포함)", inline=False)
                embed.add_field(name="상환 기한", value=f"<t:{int(due_date.timestamp())}:F>", inline=False)
                embed.add_field(name="전용 채널", value=channel.mention, inline=False)
                embed.set_footer(text="상환은 전용 채널에서 버튼을 통해 가능합니다.")

                await user.send(embed=embed)
            except discord.Forbidden:
                self.logger.warning(f"{user.id}님에게 대출 안내 DM을 보낼 수 없습니다.")

        except Exception as e:
            self.logger.error(f"대출 발행 중 오류 발생: {e}")
            await interaction.followup.send(f"❌ 대출 발행 중 오류가 발생했습니다: {e}", ephemeral=True)

    @app_commands.command(name="대출정보", description="현재 대출 상태를 확인합니다.")
    async def loan_info(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            query = "SELECT * FROM user_loans WHERE user_id = $1 AND guild_id = $2 AND status IN ('active', 'defaulted')"
            loan = await self.bot.pool.fetchrow(query, interaction.user.id, interaction.guild.id)

            if not loan:
                return await interaction.followup.send("현재 활성 상태의 대출이 없습니다.", ephemeral=True)

            status_emoji = "🟢 활성" if loan['status'] == 'active' else "🔴 연체"
            embed = discord.Embed(
                title=f"{interaction.user.display_name}님의 대출 정보",
                color=discord.Color.blue() if loan['status'] == 'active' else discord.Color.red(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="상태", value=status_emoji, inline=True)
            embed.add_field(name="원금", value=f"{loan['principal_amount']:,} 코인", inline=True)
            embed.add_field(name="남은 상환액", value=f"{loan['remaining_amount']:,} 코인", inline=True)
            embed.add_field(name="이자율", value=f"{loan['interest_rate']}%", inline=True)

            due_date = loan['due_date']
            if due_date.tzinfo is None:
                due_date = due_date.replace(tzinfo=timezone.utc)

            embed.add_field(name="상환 기한", value=f"<t:{int(due_date.timestamp())}:R>", inline=True)
            embed.add_field(name="발행일", value=f"<t:{int(loan['issued_at'].timestamp())}:f>", inline=True)

            if loan['channel_id']:
                channel = self.bot.get_channel(loan['channel_id'])
                if channel:
                    embed.add_field(name="전용 채널", value=channel.mention, inline=False)

            embed.set_footer(text=f"대출 ID: {loan['loan_id']}")
            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            self.logger.error(f"대출 정보 조회 중 오류 발생: {e}")
            await interaction.followup.send(f"❌ 대출 정보 조회 중 오류가 발생했습니다: {e}", ephemeral=True)

    @app_commands.command(name="대출상환", description="대출금을 상환합니다.")
    @app_commands.describe(amount="상환할 금액")
    async def repay_loan(self, interaction: discord.Interaction, amount: int):
        if amount <= 0:
            return await interaction.response.send_message("❌ 상환 금액은 0보다 커야 합니다.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        try:
            # Find user's loan
            query = "SELECT loan_id FROM user_loans WHERE user_id = $1 AND guild_id = $2 AND status IN ('active', 'defaulted')"
            loan = await self.bot.pool.fetchrow(query, interaction.user.id, interaction.guild.id)
            if not loan:
                return await interaction.followup.send("상환할 대출이 없습니다.", ephemeral=True)

            await self.process_repayment(interaction, loan['loan_id'], amount)

        except Exception as e:
            self.logger.error(f"대출 상환 중 오류 발생: {e}")
            await interaction.followup.send(f"❌ 대출 상환 중 오류가 발생했습니다: {e}", ephemeral=True)

    @app_commands.command(name="대출목록", description="모든 대출 목록을 확인합니다. (관리자 전용)")
    async def list_loans(self, interaction: discord.Interaction):
        if not self.has_admin_permissions(interaction.user):
            return await interaction.response.send_message("❌ 이 명령어를 사용할 권한이 없습니다.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        try:
            query = """
                SELECT loan_id, user_id, principal_amount, remaining_amount, interest_rate, status, due_date, issued_at, channel_id
                FROM user_loans 
                WHERE guild_id = $1 AND status IN ('active', 'defaulted')
                ORDER BY issued_at DESC
                LIMIT 20
            """
            loans = await self.bot.pool.fetch(query, interaction.guild.id)

            if not loans:
                return await interaction.followup.send("현재 활성 상태의 대출이 없습니다.", ephemeral=True)

            embed = discord.Embed(
                title=f"📋 {interaction.guild.name} 대출 목록",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )

            for loan in loans:
                user = self.bot.get_user(loan['user_id'])
                user_name = user.display_name if user else f"Unknown ({loan['user_id']})"
                status_emoji = "🟢" if loan['status'] == 'active' else "🔴"

                due_date = loan['due_date']
                if due_date.tzinfo is None:
                    due_date = due_date.replace(tzinfo=timezone.utc)

                channel_link = ""
                if loan['channel_id']:
                    channel = self.bot.get_channel(loan['channel_id'])
                    if channel:
                        channel_link = f"\n🔗 {channel.mention}"

                embed.add_field(
                    name=f"{status_emoji} {user_name} (ID: {loan['loan_id']})",
                    value=f"원금: {loan['principal_amount']:,}\n남은액: {loan['remaining_amount']:,}\n기한: <t:{int(due_date.timestamp())}:R>{channel_link}",
                    inline=True
                )

            embed.set_footer(text="최근 20개의 대출만 표시됩니다.")
            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            self.logger.error(f"대출 목록 조회 중 오류 발생: {e}")
            await interaction.followup.send(f"❌ 대출 목록 조회 중 오류가 발생했습니다: {e}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(LoanCog(bot))