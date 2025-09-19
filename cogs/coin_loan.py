import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timezone, timedelta

# Make sure to have these utility files or adjust the imports
from utils.logger import get_logger
from utils import config


class LoanCog(commands.Cog):
    """A cog for handling an admin-issued loan system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = get_logger("대출 시스템")

        # Start the background task after the bot is ready
        self.bot.loop.create_task(self.wait_and_start_tasks())

    async def wait_and_start_tasks(self):
        """Wait for the bot to be ready before setting up tables and starting tasks."""
        await self.bot.wait_until_ready()
        await self.setup_loan_tables()
        self.check_overdue_loans.start()
        self.logger.info("대출 시스템 Cog가 초기화되고 백그라운드 작업이 시작되었습니다.")

    async def setup_loan_tables(self):
        """Creates the necessary database table for the loan system."""
        try:
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS user_loans (
                    loan_id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    guild_id BIGINT NOT NULL,
                    principal_amount BIGINT NOT NULL,
                    remaining_amount BIGINT NOT NULL,
                    interest_rate NUMERIC(5, 2) NOT NULL,
                    status VARCHAR(20) DEFAULT 'active', -- 'active', 'paid', 'defaulted'
                    due_date TIMESTAMP NOT NULL,
                    issued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            self.logger.info("✅ 대출 데이터베이스 테이블이 준비되었습니다.")
        except Exception as e:
            self.logger.error(f"❌ 대출 테이블 설정 실패: {e}")

    # Helper function to check for admin permissions
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

    @tasks.loop(hours=24)
    async def check_overdue_loans(self):
        """Daily check for loans that have passed their due date."""
        now = datetime.now(timezone.utc)
        self.logger.info("연체된 대출을 확인하는 중...")
        try:
            query = "SELECT loan_id, user_id FROM user_loans WHERE status = 'active' AND due_date < $1"
            overdue_loans = await self.bot.pool.fetch(query, now)

            for loan in overdue_loans:
                update_query = "UPDATE user_loans SET status = 'defaulted' WHERE loan_id = $1"
                await self.bot.pool.execute(update_query, loan['loan_id'])
                self.logger.info(f"대출 ID {loan['loan_id']} (사용자: {loan['user_id']})가 'defaulted'로 변경되었습니다.")
                # Optional: Send a DM to the user here
        except Exception as e:
            self.logger.error(f"연체된 대출 확인 중 오류 발생: {e}")

    @app_commands.command(name="loan-issue", description="사용자에게 대출을 발행합니다. (관리자 전용)")
    @app_commands.describe(
        user="대출을 받을 사용자",
        amount="대출 원금",
        interest="이자율 (%)",
        days_due="상환 기한 (일)"
    )
    async def issue_loan(self, interaction: discord.Interaction, user: discord.Member, amount: int, interest: float,
                         days_due: int):
        if not self.has_admin_permissions(interaction.user):
            return await interaction.response.send_message("❌ 이 명령어를 사용할 권한이 없습니다.", ephemeral=True)

        if amount <= 0 or interest < 0 or days_due <= 0:
            return await interaction.response.send_message("❌ 유효하지 않은 입력값입니다. 모든 값은 0보다 커야 합니다.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        coins_cog = self.bot.get_cog('CoinsCog')
        if not coins_cog:
            return await interaction.followup.send("❌ 코인 시스템을 찾을 수 없습니다!", ephemeral=True)

        due_date = datetime.now(timezone.utc) + timedelta(days=days_due)
        total_repayment = amount + int(amount * (interest / 100))

        query = """
            INSERT INTO user_loans (user_id, guild_id, principal_amount, remaining_amount, interest_rate, due_date, status)
            VALUES ($1, $2, $3, $4, $5, $6, 'active')
        """
        await self.bot.pool.execute(query, user.id, interaction.guild_id, amount, total_repayment, interest, due_date)

        await coins_cog.add_coins(user.id, interaction.guild_id, amount, "loan_issued",
                                  f"Loan issued by {interaction.user.display_name}")  #

        await interaction.followup.send(
            f"✅ {user.mention}님에게 {amount:,} 코인 대출을 발행했습니다. 상환할 총액은 {total_repayment:,} 코인이며, 기한은 {days_due}일입니다.")

        try:
            embed = discord.Embed(
                title=f"{interaction.guild.name} 대출 승인",
                description=f"관리자에 의해 대출이 승인되었습니다.",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="대출 원금", value=f"{amount:,} 코인", inline=False)
            embed.add_field(name="총 상환액", value=f"{total_repayment:,} 코인 ({interest}% 이자 포함)", inline=False)
            embed.add_field(name="상환 기한", value=f"<t:{int(due_date.timestamp())}:F>", inline=False)
            await user.send(embed=embed)
        except discord.Forbidden:
            self.logger.warning(f"{user.id}님에게 대출 안내 DM을 보낼 수 없습니다.")

    @app_commands.command(name="loan-info", description="현재 대출 상태를 확인합니다.")
    async def loan_info(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        query = "SELECT * FROM user_loans WHERE user_id = $1 AND guild_id = $2 AND status IN ('active', 'defaulted')"
        loan = await self.bot.pool.fetchrow(query, interaction.user.id, interaction.guild.id)

        if not loan:
            return await interaction.followup.send("현재 활성 상태의 대출이 없습니다.", ephemeral=True)

        status_emoji = "🟢 활성" if loan['status'] == 'active' else "🔴 연체"
        embed = discord.Embed(
            title=f"{interaction.user.display_name}님의 대출 정보",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="상태", value=status_emoji, inline=True)
        embed.add_field(name="남은 상환액", value=f"{loan['remaining_amount']:,} 코인", inline=True)
        embed.add_field(name="상환 기한", value=f"<t:{int(loan['due_date'].timestamp())}:R>", inline=True)
        embed.set_footer(text=f"대출 ID: {loan['loan_id']}")

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="loan-repay", description="대출금을 상환합니다.")
    @app_commands.describe(amount="상환할 금액")
    async def repay_loan(self, interaction: discord.Interaction, amount: int):
        if amount <= 0:
            return await interaction.response.send_message("❌ 상환 금액은 0보다 커야 합니다.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        coins_cog = self.bot.get_cog('CoinsCog')
        if not coins_cog:
            return await interaction.followup.send("❌ 코인 시스템을 찾을 수 없습니다!", ephemeral=True)

        # Find the user's loan
        query = "SELECT loan_id, remaining_amount FROM user_loans WHERE user_id = $1 AND guild_id = $2 AND status IN ('active', 'defaulted')"
        loan = await self.bot.pool.fetchrow(query, interaction.user.id, interaction.guild.id)
        if not loan:
            return await interaction.followup.send("상환할 대출이 없습니다.", ephemeral=True)

        # Ensure they don't overpay
        payment_amount = min(amount, loan['remaining_amount'])

        # Check balance
        user_balance = await coins_cog.get_user_coins(interaction.user.id, interaction.guild.id)  #
        if user_balance < payment_amount:
            return await interaction.followup.send(f"❌ 코인이 부족합니다. 필요: {payment_amount:,}, 보유: {user_balance:,}",
                                                   ephemeral=True)

        # Process payment
        success = await coins_cog.remove_coins(interaction.user.id, interaction.guild.id, payment_amount,
                                               "loan_repayment", f"Payment for loan ID {loan['loan_id']}")  #
        if not success:
            return await interaction.followup.send("❌ 상환 처리 중 오류가 발생했습니다.", ephemeral=True)

        new_remaining = loan['remaining_amount'] - payment_amount
        if new_remaining <= 0:
            update_query = "UPDATE user_loans SET remaining_amount = 0, status = 'paid' WHERE loan_id = $1"
            await self.bot.pool.execute(update_query, loan['loan_id'])
            await interaction.followup.send(f"🎉 **{payment_amount:,} 코인**을 상환하여 대출을 모두 갚았습니다! 축하합니다!", ephemeral=True)
        else:
            update_query = "UPDATE user_loans SET remaining_amount = $1 WHERE loan_id = $1"
            await self.bot.pool.execute(update_query, new_remaining, loan['loan_id'])
            await interaction.followup.send(f"✅ **{payment_amount:,} 코인**을 상환했습니다. 남은 금액: **{new_remaining:,} 코인**",
                                            ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(LoanCog(bot))