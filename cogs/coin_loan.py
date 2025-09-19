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
    amount = discord.ui.TextInput(
        label="대출 금액",
        placeholder="신청할 대출 금액을 입력하세요 (예: 10000)",
        min_length=1,
        max_length=10,
    )

    interest = discord.ui.TextInput(
        label="희망 이자율 (%)",
        placeholder="희망하는 이자율을 입력하세요 (예: 5.5)",
        min_length=1,
        max_length=5,
    )

    days_due = discord.ui.TextInput(
        label="상환 기간 (일)",
        placeholder="상환 기간을 일 단위로 입력하세요 (예: 30)",
        min_length=1,
        max_length=3,
    )

    reason = discord.ui.TextInput(
        label="대출 사유",
        placeholder="대출이 필요한 이유를 간단히 설명해주세요",
        style=discord.TextStyle.paragraph,
        min_length=10,
        max_length=500,
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

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
        emoji="✅",
        custom_id=f"loan_approve"
    )
    async def approve_loan(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog.has_admin_permissions(interaction.user):
            return await interaction.response.send_message("❌ 권한이 없습니다.", ephemeral=True)

        await self.cog.handle_loan_approval(interaction, self.request_id)

    @discord.ui.button(
        label="역제안",
        style=discord.ButtonStyle.secondary,
        emoji="🔄",
        custom_id=f"loan_counter"
    )
    async def counter_offer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.cog.has_admin_permissions(interaction.user):
            return await interaction.response.send_message("❌ 권한이 없습니다.", ephemeral=True)

        await self.cog.handle_counter_offer(interaction, self.request_id)

    @discord.ui.button(
        label="거부",
        style=discord.ButtonStyle.danger,
        emoji="❌",
        custom_id=f"loan_deny"
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
        emoji="💳",
        custom_id=f"loan_repay"
    )
    async def repay_loan(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = RepaymentModal(self.cog, self.loan_id)
        await interaction.response.send_modal(modal)


class RepaymentModal(discord.ui.Modal, title="대출 상환"):
    """Modal for loan repayment"""
    amount = discord.ui.TextInput(
        label="상환 금액",
        placeholder="상환할 금액을 입력하세요",
        min_length=1,
        max_length=10,
    )

    def __init__(self, cog, loan_id: int):
        super().__init__()
        self.cog = cog
        self.loan_id = loan_id

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
    amount = discord.ui.TextInput(
        label="대출 금액",
        placeholder="제안할 대출 금액",
        min_length=1,
        max_length=10,
    )

    interest = discord.ui.TextInput(
        label="이자율 (%)",
        placeholder="제안할 이자율",
        min_length=1,
        max_length=5,
    )

    days_due = discord.ui.TextInput(
        label="상환 기간 (일)",
        placeholder="제안할 상환 기간",
        min_length=1,
        max_length=3,
    )

    note = discord.ui.TextInput(
        label="추가 메모",
        placeholder="역제안 사유나 추가 설명",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(self, cog, request_id: int):
        super().__init__()
        self.cog = cog
        self.request_id = request_id

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
        await self.bot.wait_until_ready()
        await self.setup_loan_tables()
        await self.setup_request_interface()
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
        admin_role_id = config.get_role_id(member.guild.id, 'admin_role')
        if admin_role_id and discord.utils.get(member.roles, id=admin_role_id):
            return True
        staff_role_id = config.get_role_id(member.guild.id, 'staff_role')
        if staff_role_id and discord.utils.get(member.roles, id=staff_role_id):
            return True
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
                title="🔍 새로운 대출 신청",
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

            # Issue the loan
            coins_cog = self.bot.get_cog('CoinsCog')
            if not coins_cog:
                return await interaction.followup.send("❌ 코인 시스템을 찾을 수 없습니다.", ephemeral=True)

            # Create loan channel first
            channel = await self.create_loan_channel(interaction.guild, user, request['amount'],
                                                     request['interest_rate'],
                                                     request['days_due'])
            if not channel:
                return await interaction.followup.send("❌ 대출 채널 생성에 실패했습니다.", ephemeral=True)

            # Calculate loan details
            utc = pytz.UTC
            now_aware = datetime.now(utc)
            now_naive = now_aware.replace(tzinfo=None)
            due_date_naive = now_naive + timedelta(days=request['days_due'])
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
                due_date_naive, channel.id
            )

            # Give coins to user
            success = await coins_cog.add_coins(
                request['user_id'], request['guild_id'], request['amount'],
                "loan_issued", f"Loan approved by {interaction.user.display_name}"
            )

            if not success:
                # Rollback
                await self.bot.pool.execute("DELETE FROM user_loans WHERE loan_id = $1", loan_record['loan_id'])
                await channel.delete()
                return await interaction.followup.send("❌ 코인 지급에 실패했습니다.", ephemeral=True)

            # Update request status
            await self.bot.pool.execute(
                "UPDATE loan_requests SET status = 'approved', channel_id = $1 WHERE request_id = $2",
                channel.id, request_id
            )

            # Update loan channel with loan info
            await self.update_loan_channel(channel, loan_record['loan_id'])

            # Disable buttons on original message
            for item in interaction.message.components:
                for component in item.children:
                    component.disabled = True

            embed = interaction.message.embeds[0]
            embed.color = discord.Color.green()
            embed.title = "✅ 대출 승인됨"
            embed.add_field(name="처리자", value=interaction.user.display_name, inline=True)
            embed.add_field(name="대출 채널", value=channel.mention, inline=True)

            await interaction.message.edit(embed=embed, view=None)
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
            embed = interaction.message.embeds[0]
            embed.color = discord.Color.red()
            embed.title = "❌ 대출 거부됨"
            embed.add_field(name="처리자", value=interaction.user.display_name, inline=True)

            await interaction.message.edit(embed=embed, view=None)
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

    async def create_loan_channel(self, guild: discord.Guild, user: discord.User, amount: int, interest_rate: float,
                                  days: int) -> discord.TextChannel:
        """Create a private loan channel"""
        try:
            category = guild.get_channel(self.LOAN_CATEGORY)

            if not category:
                self.logger.error(f"대출 카테고리를 찾을 수 없습니다: {self.LOAN_CATEGORY}")
                return None

            # Create channel
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }

            # Add admin roles
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

            channel_name = f"🚨┆{user.display_name}님의-대출-정보"
            channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"{user.display_name}님의 개인 대출 관리 채널"
            )

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
        """Create negotiation channel for counter offers - DEBUG VERSION"""
        await interaction.response.defer(ephemeral=True)

        try:
            # DEBUG: Log the start of the process
            self.logger.info(f"Starting negotiation channel creation for request_id: {request_id}")

            # Get original request
            request_query = "SELECT * FROM loan_requests WHERE request_id = $1"
            request = await self.bot.pool.fetchrow(request_query, request_id)

            if not request:
                self.logger.error(f"Request not found: {request_id}")
                return await interaction.followup.send("❌ 유효하지 않은 대출 신청입니다.", ephemeral=True)

            user = self.bot.get_user(request['user_id'])
            if not user:
                self.logger.error(f"User not found: {request['user_id']}")
                return await interaction.followup.send("❌ 사용자를 찾을 수 없습니다.", ephemeral=True)

            # DEBUG: Log user found
            self.logger.info(f"Found user: {user.display_name} ({user.id})")

            # Create negotiation channel in the category
            guild = interaction.guild
            category = guild.get_channel(self.LOAN_CATEGORY)

            # DEBUG: Check category
            self.logger.info(f"Looking for category ID: {self.LOAN_CATEGORY}")
            if not category:
                self.logger.error(f"Category not found: {self.LOAN_CATEGORY}")
                return await interaction.followup.send(f"❌ 대출 카테고리를 찾을 수 없습니다. (ID: {self.LOAN_CATEGORY})",
                                                       ephemeral=True)

            if not isinstance(category, discord.CategoryChannel):
                self.logger.error(f"Channel {self.LOAN_CATEGORY} is not a category channel, type: {type(category)}")
                return await interaction.followup.send("❌ 지정된 채널이 카테고리가 아닙니다.", ephemeral=True)

            # DEBUG: Log category found
            self.logger.info(f"Found category: {category.name} ({category.id})")

            # Check bot permissions in category
            bot_perms = category.permissions_for(guild.me)
            if not bot_perms.manage_channels:
                self.logger.error("Bot doesn't have manage_channels permission in category")
                return await interaction.followup.send("❌ 봇이 채널을 생성할 권한이 없습니다.", ephemeral=True)

            # Create channel overwrites
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }

            # DEBUG: Log default overwrites created
            self.logger.info("Created default overwrites")

            # Add admin roles
            admin_role_id = config.get_role_id(guild.id, 'admin_role')
            self.logger.info(f"Admin role ID from config: {admin_role_id}")

            if admin_role_id:
                admin_role = guild.get_role(admin_role_id)
                if admin_role:
                    overwrites[admin_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                    self.logger.info(f"Added admin role to overwrites: {admin_role.name}")
                else:
                    self.logger.warning(f"Admin role not found: {admin_role_id}")

            staff_role_id = config.get_role_id(guild.id, 'staff_role')
            self.logger.info(f"Staff role ID from config: {staff_role_id}")

            if staff_role_id:
                staff_role = guild.get_role(staff_role_id)
                if staff_role:
                    overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                    self.logger.info(f"Added staff role to overwrites: {staff_role.name}")
                else:
                    self.logger.warning(f"Staff role not found: {staff_role_id}")

            # Create negotiation channel - simplified name for testing
            channel_name = f"negotiation-{user.id}"  # Simple name for debugging

            self.logger.info(f"Creating channel with name: {channel_name}")
            self.logger.info(f"Category permissions for bot: {category.permissions_for(guild.me)}")

            # Attempt channel creation
            try:
                channel = await guild.create_text_channel(
                    name=channel_name,
                    category=category,
                    overwrites=overwrites,
                    topic=f"Loan negotiation for {user.display_name}"
                )
                self.logger.info(f"Successfully created channel: {channel.name} ({channel.id})")
            except discord.HTTPException as e:
                self.logger.error(f"HTTPException creating channel: {e}")
                self.logger.error(f"HTTP Exception details: {e.status}, {e.code}, {e.text}")
                return await interaction.followup.send(f"❌ 채널 생성 중 HTTP 오류: {e}", ephemeral=True)
            except discord.Forbidden as e:
                self.logger.error(f"Forbidden creating channel: {e}")
                self.logger.error(f"Bot permissions in category: {category.permissions_for(guild.me)}")
                return await interaction.followup.send("❌ 채널 생성 권한이 없습니다.", ephemeral=True)
            except Exception as e:
                self.logger.error(f"Unexpected error creating channel: {e}")
                self.logger.error(f"Exception type: {type(e).__name__}")
                import traceback
                self.logger.error(f"Traceback: {traceback.format_exc()}")
                return await interaction.followup.send(f"❌ 예상치 못한 오류: {e}", ephemeral=True)

            # Update request status
            try:
                await self.bot.pool.execute(
                    "UPDATE loan_requests SET status = 'negotiating', channel_id = $1 WHERE request_id = $2",
                    channel.id, request_id
                )
                self.logger.info(f"Updated request {request_id} status to negotiating")
            except Exception as e:
                self.logger.error(f"Database update error: {e}")
                # Don't return here, continue with the process

            # Create negotiation embed
            embed = discord.Embed(
                title="📄 대출 역제안",
                description=f"{user.mention}님의 대출 신청에 대한 관리자 역제안입니다.",
                color=discord.Color.orange(),
                timestamp=datetime.now(timezone.utc)
            )

            # Original terms
            embed.add_field(
                name="📋 원래 신청 조건",
                value=f"**금액:** {request['amount']:,} 코인\n**이자율:** {request['interest_rate']}%\n**기간:** {request['days_due']}일",
                inline=True
            )

            # Counter offer terms
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

            # Send embed to channel
            try:
                await channel.send(f"{user.mention} 관리자들", embed=embed)
                self.logger.info("Successfully sent embed to negotiation channel")
            except Exception as e:
                self.logger.error(f"Error sending embed to channel: {e}")

            # Update original message
            try:
                orig_embed = interaction.message.embeds[0]
                orig_embed.color = discord.Color.orange()
                orig_embed.title = "📄 역제안 진행 중"
                orig_embed.add_field(name="처리자", value=interaction.user.display_name, inline=True)
                orig_embed.add_field(name="협상 채널", value=channel.mention, inline=True)

                await interaction.message.edit(embed=orig_embed, view=None)
                self.logger.info("Updated original message")
            except Exception as e:
                self.logger.error(f"Error updating original message: {e}")

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
                self.logger.info("Sent DM to user")
            except Exception as e:
                self.logger.warning(f"Could not send DM to user: {e}")

        except Exception as e:
            self.logger.error(f"협상 채널 생성 실패: {e}")
            self.logger.error(f"Exception type: {type(e).__name__}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            await interaction.followup.send(f"❌ 협상 채널 생성 중 오류가 발생했습니다: {e}", ephemeral=True)

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
        current_time = datetime.utcnow()
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

    # Keep original admin commands for backwards compatibility
    @app_commands.command(name="대출발행", description="사용자에게 대출을 발행합니다. (관리자 전용)")
    @app_commands.describe(
        user="대출을 받을 사용자",
        amount="대출 원금",
        interest="이자율 (%)",
        days_due="상환 기한 (일)"
    )
    async def issue_loan(self, interaction: discord.Interaction, user: discord.Member, amount: int,
                         interest: float, days_due: int):
        # Check permissions first
        if not self.has_admin_permissions(interaction.user):
            return await interaction.response.send_message("❌ 이 명령어를 사용할 권한이 없습니다.", ephemeral=True)

        # Validate inputs
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
            utc = pytz.UTC
            now_aware = datetime.now(utc)
            now_naive = now_aware.replace(tzinfo=None)
            due_date_naive = now_naive + timedelta(days=days_due)
            total_repayment = amount + int(amount * (interest / 100))

            # Insert loan record
            query = """
                INSERT INTO user_loans (user_id, guild_id, principal_amount, remaining_amount, interest_rate, due_date, status, channel_id)
                VALUES ($1, $2, $3, $4, $5, $6, 'active', $7)
                RETURNING loan_id
            """
            loan_record = await self.bot.pool.fetchrow(
                query, user.id, interaction.guild_id, amount, total_repayment, interest, due_date_naive, channel.id
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
                due_date_aware = due_date_naive.replace(tzinfo=utc)
                embed = discord.Embed(
                    title=f"{interaction.guild.name} 대출 승인",
                    description=f"관리자에 의해 대출이 승인되었습니다.",
                    color=discord.Color.green(),
                    timestamp=now_aware
                )
                embed.add_field(name="대출 원금", value=f"{amount:,} 코인", inline=False)
                embed.add_field(name="총 상환액", value=f"{total_repayment:,} 코인 ({interest}% 이자 포함)", inline=False)
                embed.add_field(name="상환 기한", value=f"<t:{int(due_date_aware.timestamp())}:F>", inline=False)
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
                        channel_link = f"\n📝 {channel.mention}"

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