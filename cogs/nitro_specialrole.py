# cogs/nitro_specialrole.py
import discord
from discord.ext import commands
import json
import os
import asyncio
from typing import Dict

from utils.logger import get_logger

# --- Constants ---
# The channel where the control panel message will be posted.
SPECIAL_ROLE_CHANNEL_ID = 1366767855462518825
# The role that grants eligibility, in addition to being a server booster.
ELIGIBILITY_ROLE_ID = 1417771791384051823
# The two exclusive roles users can choose from.
ROLE_ONE_ID = 1417780157615181865
ROLE_TWO_ID = 1417779863464448080
# The Guild ID
GUILD_ID = 1059211805567746090


class SpecialRoleControlView(discord.ui.View):
    """A persistent view with buttons for choosing one of two special roles."""

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog
        self.role_ids = [ROLE_ONE_ID, ROLE_TWO_ID]

    async def _handle_role_selection(self, interaction: discord.Interaction, target_role_id: int):
        """Core logic for selecting and swapping roles."""
        await interaction.response.defer(ephemeral=True)
        member = interaction.user
        guild = interaction.guild

        if not self.cog.is_eligible_user(member):
            embed = discord.Embed(
                title="❌ 권한 부족",
                description="이 기능은 **서버 부스터** 또는 **특별 역할**을 가진 분만 사용할 수 있습니다.",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        target_role = guild.get_role(target_role_id)
        if not target_role:
            await interaction.followup.send("오류: 역할을 찾을 수 없습니다. 관리자에게 문의하세요.", ephemeral=True)
            return

        # Check if the user already has the target role
        if any(role.id == target_role_id for role in member.roles):
            await interaction.followup.send(f"이미 {target_role.mention} 역할을 보유하고 있습니다.", ephemeral=True)
            return

        # Find and remove the other special role if it exists
        roles_to_remove = [role for role in member.roles if role.id in self.role_ids]
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove, reason="특별 역할 교체")

        # Add the new role
        await member.add_roles(target_role, reason="특별 역할 선택")

        embed = discord.Embed(
            title="✅ 역할 변경 완료",
            description=f"이제 {target_role.mention} 역할을 보유하게 되었습니다.",
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="[ UOFTS ] 역할 받기", style=discord.ButtonStyle.primary, custom_id="get_special_role_one")
    async def get_role_one(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_role_selection(interaction, ROLE_ONE_ID)

    @discord.ui.button(label="[ UT ] 역할 받기", style=discord.ButtonStyle.primary, custom_id="get_special_role_two")
    async def get_role_two(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_role_selection(interaction, ROLE_TWO_ID)

    @discord.ui.button(label="역할 제거", style=discord.ButtonStyle.danger, custom_id="remove_special_role")
    async def remove_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        member = interaction.user

        roles_to_remove = [role for role in member.roles if role.id in self.role_ids]

        if not roles_to_remove:
            await interaction.followup.send("제거할 특별 역할이 없습니다.", ephemeral=True)
            return

        await member.remove_roles(*roles_to_remove, reason="사용자 요청")

        embed = discord.Embed(
            title="🗑️ 역할 제거 완료",
            description="보유하고 있던 특별 역할이 제거되었습니다.",
            color=discord.Color.gold()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


class BoosterSpecialRoleCog(commands.Cog):
    """Cog for managing special, exclusive roles for boosters."""

    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("부스터특별역할")
        self.data_file = 'booster_special_role_data.json'
        self.message_id = None
        self.load_data()
        self.persistent_view = SpecialRoleControlView(self)
        self.role_ids = [ROLE_ONE_ID, ROLE_TWO_ID]

    def load_data(self):
        try:
            with open(self.data_file, 'r') as f:
                data = json.load(f)
                self.message_id = data.get('message_id', None)
        except FileNotFoundError:
            pass

    def save_data(self):
        data = {'message_id': self.message_id}
        with open(self.data_file, 'w') as f:
            json.dump(data, f)

    async def cog_load(self):
        self.bot.add_view(self.persistent_view)
        asyncio.create_task(self.validate_message())

    async def validate_message(self):
        await self.bot.wait_until_ready()
        try:
            guild = self.bot.get_guild(GUILD_ID)
            if not guild:
                return

            channel = guild.get_channel(SPECIAL_ROLE_CHANNEL_ID)
            if not channel:
                return

            message_exists = False
            if self.message_id:
                try:
                    msg = await channel.fetch_message(self.message_id)
                    if msg.embeds and msg.embeds[0].title == "🌟 부스터 전용 특별 역할":
                        message_exists = True
                    else:
                        await msg.delete()
                except (discord.NotFound, discord.Forbidden):
                    pass

            if not message_exists:
                await self._create_message(channel)

        except Exception as e:
            self.logger.error(f"Error validating special role message: {e}", exc_info=True)

    async def _create_message(self, channel: discord.TextChannel):
        """Creates the control panel message."""
        role1 = channel.guild.get_role(ROLE_ONE_ID)
        role2 = channel.guild.get_role(ROLE_TWO_ID)

        embed = discord.Embed(
            title="🌟 부스터 전용 특별 역할",
            description=(
                "서버 부스터 및 특별 역할 보유자를 위한 전용 역할입니다!\n"
                "아래 버튼을 눌러 원하는 역할 중 **하나**를 선택하세요."
            ),
            color=discord.Color.purple()
        )
        embed.add_field(
            name="선택 가능한 역할",
            value=f"• {role1.mention if role1 else 'UOFTS 역할'}\n• {role2.mention if role2 else 'UT 역할'}",
            inline=False
        )
        embed.add_field(
            name="⚠️ 중요 규칙",
            value=(
                "• 두 역할 중 하나만 가질 수 있습니다.\n"
                "• 다른 역할을 선택하면 기존 역할은 자동으로 제거됩니다.\n"
                "• 부스터 자격을 잃으면 역할이 자동으로 제거됩니다."
            ),
            inline=False
        )
        embed.set_footer(text="부스터 혜택을 즐겨보세요!")

        try:
            message = await channel.send(embed=embed, view=self.persistent_view)
            self.message_id = message.id
            self.save_data()
            self.logger.info(f"Special role message created in {channel.name}")
        except discord.Forbidden:
            self.logger.error(f"No permission to send messages in {channel.name}")
        except Exception as e:
            self.logger.error(f"Error creating special role message: {e}", exc_info=True)

    def is_eligible_user(self, member: discord.Member) -> bool:
        """Check if a member is a server booster or has the eligibility role."""
        is_booster = member.premium_since is not None
        has_special_role = any(role.id == ELIGIBILITY_ROLE_ID for role in member.roles)
        return is_booster or has_special_role

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Remove the special role if a member loses booster eligibility."""
        was_eligible = self.is_eligible_user(before)
        is_eligible = self.is_eligible_user(after)

        if was_eligible and not is_eligible:
            roles_to_remove = [role for role in after.roles if role.id in self.role_ids]
            if roles_to_remove:
                await after.remove_roles(*roles_to_remove, reason="부스터 자격 상실")
                self.logger.info(f"{after.display_name} lost eligibility, removed special role(s).")

    @commands.command(name="setup-special-role")
    @commands.has_permissions(administrator=True)
    async def setup_special_role_command(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """(Admin) Sets up the special role message."""
        if channel is None:
            channel = ctx.guild.get_channel(SPECIAL_ROLE_CHANNEL_ID)
            if channel is None:
                await ctx.send("❌ 지정된 채널을 찾을 수 없습니다.")
                return

        await self._create_message(channel)
        await ctx.send(f"✅ 특별 역할 선택 메시지가 {channel.mention}에 설정되었습니다.", delete_after=10)


async def setup(bot):
    await bot.add_cog(BoosterSpecialRoleCog(bot))