# cogs/booster_voice.py
import discord
from discord.ext import commands
from discord import app_commands
from typing import Dict, Optional
import asyncio
from datetime import datetime, timezone
import json
import os

from utils.logger import get_logger
from utils.config import get_server_setting


class BoosterVoiceSystem:
    """Manages booster voice channels for a guild"""

    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.user_channels: Dict[int, int] = {}  # user_id -> channel_id
        self.channel_owners: Dict[int, int] = {}  # channel_id -> user_id


class BoosterVoiceCog(commands.Cog):
    """Booster voice channel management system"""

    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("부스터음성")
        self.guild_systems: Dict[int, BoosterVoiceSystem] = {}
        # New Category ID
        self.booster_voice_category_id = 1207987828370440192
        self.data_file = 'booster_voice_data.json'
        self.booster_message_id = None
        self.booster_channel_id = 1366767855462518825  # The specific channel ID from user's request
        self.voice_creator_role_id = 1417771791384051823 # New role ID
        self.load_data()

        # Initialize the persistent view
        self.persistent_view = BoosterVoiceControlView(self)

    def load_data(self):
        """Loads persistent data from a JSON file."""
        try:
            with open(self.data_file, 'r') as f:
                data = json.load(f)
                self.booster_message_id = data.get('booster_message_id', None)
        except FileNotFoundError:
            pass

    def save_data(self):
        """Saves persistent data to a JSON file."""
        data = {'booster_message_id': self.booster_message_id}
        with open(self.data_file, 'w') as f:
            json.dump(data, f)

    async def cog_load(self):
        """Called when cog loads - adds persistent view and checks for message."""
        self.bot.add_view(self.persistent_view)
        # Schedule message validation after bot is ready
        asyncio.create_task(self.validate_booster_message())

    async def validate_booster_message(self):
        """Check if the booster message exists, recreate if missing."""
        # Wait for bot to be ready
        await self.bot.wait_until_ready()

        try:
            guild = self.bot.get_guild(1059211805567746090)  # NOTE: Replace with your actual guild ID
            if not guild:
                return

            channel = guild.get_channel(self.booster_channel_id)
            if not channel:
                return

            # Check if tracked message exists
            message_exists = False
            if self.booster_message_id:
                try:
                    message = await channel.fetch_message(self.booster_message_id)
                    # Verify it has the correct embed and view (optional but good practice)
                    if message.embeds and message.embeds[0].title == "🌟 부스터 전용 음성 채널":
                        message_exists = True
                    else:
                        # Message exists but wrong content, delete it
                        await message.delete()
                        message_exists = False
                except (discord.NotFound, discord.Forbidden):
                    message_exists = False

            # Recreate message if missing or invalid
            if not message_exists:
                await self._create_booster_message(channel)

        except Exception as e:
            self.logger.error(f"Error validating booster message: {e}", exc_info=True)

    async def _create_booster_message(self, channel):
        """Create the booster message embed and view."""
        embed = discord.Embed(
            title="🌟 부스터 전용 음성 채널",
            description="서버 부스터만 사용할 수 있는 독점적인 음성 채널을 만들고 관리하세요! 아래 버튼을 눌러 시작하세요.",
            color=discord.Color.gold()
        )
        embed.add_field(
            name="사용 방법",
            value=(
                "• **'음성 채널 생성'** 버튼을 누르면 나만의 음성 채널이 생성됩니다.\n"
                "• 채널의 소유자가 되어 이름, 인원 제한 등을 자유롭게 설정할 수 있습니다.\n"
                "• **'내 채널 삭제'** 버튼으로 언제든지 채널을 제거할 수 있습니다.\n"
                "• 서버 부스트를 중단하면 채널이 자동으로 사라집니다."
            ),
            inline=False
        )
        embed.set_footer(text="부스터 특권을 즐겨보세요!")

        try:
            message = await channel.send(embed=embed, view=self.persistent_view)
            self.booster_message_id = message.id
            self.save_data()
            self.logger.info(f"Booster voice message created/recreated in {channel.name}")
        except discord.Forbidden:
            self.logger.error(f"❌ No permission to send messages in {channel.name}")
        except Exception as e:
            self.logger.error(f"❌ Error creating booster message: {e}", exc_info=True)

    def get_system(self, guild_id: int) -> BoosterVoiceSystem:
        """Get or create booster voice system for guild"""
        if guild_id not in self.guild_systems:
            self.guild_systems[guild_id] = BoosterVoiceSystem(guild_id)
        return self.guild_systems[guild_id]

    def is_eligible_creator(self, member: discord.Member) -> bool:
        """Check if member is a booster or has the designated role"""
        is_booster = member.premium_since is not None
        has_special_role = any(role.id == self.voice_creator_role_id for role in member.roles)
        return is_booster or has_special_role

    async def create_booster_channel(self, member: discord.Member, interaction: discord.Interaction = None) -> Optional[
        discord.VoiceChannel]:
        """Create a voice channel for an eligible creator with full permissions"""
        try:
            guild = member.guild
            system = self.get_system(guild.id)

            # Check if user already has a channel
            if member.id in system.user_channels:
                existing_channel = guild.get_channel(system.user_channels[member.id])
                if existing_channel:
                    if interaction:
                        await interaction.followup.send("이미 부스터 음성 채널을 보유하고 있습니다!", ephemeral=True)
                    return existing_channel
                else:
                    # Clean up dead reference
                    del system.user_channels[member.id]

            # Get the category
            category = guild.get_channel(self.booster_voice_category_id)
            if not category:
                self.logger.error(f"부스터 음성 채널 카테고리를 찾을 수 없습니다: {self.booster_voice_category_id}")
                if interaction:
                    await interaction.followup.send("음성 채널 카테고리를 찾을 수 없습니다. 관리자에게 문의하세요.", ephemeral=True)
                return None

            # New channel name format
            channel_name = f"╠❔┆{member.display_name}의 채널"

            # Set up permissions - creator gets full control
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(
                    view_channel=True,
                    connect=True
                ),
                member: discord.PermissionOverwrite(
                    view_channel=True,
                    connect=True,
                    speak=True,
                    manage_channels=True,  # Can edit channel
                    manage_permissions=True,  # Can manage who joins
                    move_members=True,  # Can move/kick members
                    mute_members=True,  # Can mute members
                    deafen_members=True,  # Can deafen members
                    set_voice_channel_status=True,
                )
            }

            # 1. Create the channel first
            voice_channel = await guild.create_voice_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                reason=f"부스터/특별 역할을 위한 전용 음성 채널"
            )

            # 2. Get the position of the channel we need to be above
            target_channel = guild.get_channel(1207988341698592788)
            if target_channel and target_channel.category == category:
                # 3. Edit the new channel's position to be above the target
                new_position = target_channel.position
                await voice_channel.edit(position=new_position)


            # Store the mapping
            system.user_channels[member.id] = voice_channel.id
            system.channel_owners[voice_channel.id] = member.id

            self.logger.info(f"부스터 음성 채널 생성됨: {member.display_name} -> {voice_channel.id}")

            if interaction:
                embed = discord.Embed(
                    title="🎉 부스터 음성 채널 생성 완료!",
                    description=f"<#{voice_channel.id}> 채널이 생성되었습니다.",
                    color=discord.Color.gold()
                )
                embed.add_field(
                    name="🎛️ 관리 권한",
                    value="• 채널 이름 변경\n• 인원 제한 설정\n• 멤버 추방/이동\n• 음소거/청음차단\n• 접근 권한 관리",
                    inline=False
                )
                embed.add_field(
                    name="⚠️ 주의사항",
                    value="서버 부스트를 중단하거나 특별 역할이 제거되면 채널이 자동으로 삭제됩니다.",
                    inline=False
                )
                embed.set_footer(text="특별한 채널을 즐겨보세요!")
                await interaction.followup.send(embed=embed, ephemeral=True)

            return voice_channel

        except Exception as e:
            self.logger.error(f"부스터 음성 채널 생성 실패: {e}", exc_info=True)
            if interaction:
                await interaction.followup.send("음성 채널 생성 중 오류가 발생했습니다.", ephemeral=True)
            return None

    async def delete_booster_channel(self, member: discord.Member, reason: str = "자격 상실") -> bool:
        """Delete a user's voice channel"""
        try:
            guild = member.guild
            system = self.get_system(guild.id)

            if member.id not in system.user_channels:
                return False

            channel_id = system.user_channels[member.id]
            channel = guild.get_channel(channel_id)

            if channel:
                # Move any members out of the channel first
                if len(channel.members) > 0:
                    # Try to find a general voice channel to move them to
                    general_channel = discord.utils.get(guild.voice_channels, name="일반")
                    if not general_channel:
                        general_channel = discord.utils.find(
                            lambda c: c != channel and not any(
                                overwrites for overwrites in c.overwrites.values()
                                if overwrites.manage_channels
                            ),
                            guild.voice_channels
                        )

                    for member_in_channel in channel.members:
                        if general_channel:
                            try:
                                await member_in_channel.move_to(general_channel)
                            except:
                                try:
                                    await member_in_channel.move_to(None)  # Disconnect
                                except:
                                    pass
                        else:
                            try:
                                await member_in_channel.move_to(None)  # Disconnect
                            except:
                                pass

                await channel.delete(reason=reason)
                self.logger.info(f"부스터 음성 채널 삭제됨: {member.display_name} ({reason})")

            # Clean up mappings
            del system.user_channels[member.id]
            if channel_id in system.channel_owners:
                del system.channel_owners[channel_id]

            return True

        except Exception as e:
            self.logger.error(f"부스터 음성 채널 삭제 실패: {e}", exc_info=True)
            return False

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Handle status changes that may affect channel eligibility"""
        was_eligible = self.is_eligible_creator(before)
        is_eligible = self.is_eligible_creator(after)

        if was_eligible and not is_eligible:
            # Lost eligibility - delete their channel
            await self.delete_booster_channel(after, "자격 상실")
            self.logger.info(f"{after.display_name}의 자격이 상실되어 음성 채널이 삭제되었습니다.")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState,
                                    after: discord.VoiceState):
        """Monitor voice channel activity for auto-cleanup"""
        system = self.get_system(member.guild.id)

        # If someone left a booster channel and it's now empty, we could auto-delete
        # But for now, we'll let eligible creators keep their channels even when empty
        pass

    @app_commands.command(name="부스터음성생성", description="부스터 전용 음성 채널을 생성합니다")
    async def create_booster_voice(self, interaction: discord.Interaction):
        """Create a booster voice channel"""
        await interaction.response.defer(ephemeral=True)

        # Check if user is an eligible creator
        if not self.is_eligible_creator(interaction.user):
            embed = discord.Embed(
                title="❌ 권한 부족",
                description="이 기능은 **서버 부스터** 또는 **특별 역할**을 가진 분만 사용할 수 있습니다.",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        await self.create_booster_channel(interaction.user, interaction)

    @app_commands.command(name="부스터음성삭제", description="자신의 부스터 음성 채널을 삭제합니다")
    async def delete_booster_voice(self, interaction: discord.Interaction):
        """Delete user's booster voice channel"""
        await interaction.response.defer(ephemeral=True)

        system = self.get_system(interaction.guild.id)

        if interaction.user.id not in system.user_channels:
            await interaction.followup.send("생성된 부스터 음성 채널이 없습니다.", ephemeral=True)
            return

        success = await self.delete_booster_channel(interaction.user, "사용자 요청")

        if success:
            embed = discord.Embed(
                title="✅ 채널 삭제 완료",
                description="부스터 음성 채널이 삭제되었습니다.",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title="❌ 삭제 실패",
                description="채널 삭제 중 오류가 발생했습니다.",
                color=discord.Color.red()
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="부스터음성관리", description="부스터 음성 채널 관리 (관리자 전용)")
    async def manage_booster_voices(self, interaction: discord.Interaction):
        """Admin command to manage booster voice channels"""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("관리자만 사용할 수 있습니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        system = self.get_system(interaction.guild.id)
        guild = interaction.guild

        embed = discord.Embed(
            title="🎛️ 부스터 음성 채널 관리",
            color=discord.Color.blue()
        )

        if not system.user_channels:
            embed.description = "현재 활성 부스터 음성 채널이 없습니다."
        else:
            channel_list = []
            for user_id, channel_id in system.user_channels.items():
                user = guild.get_member(user_id)
                channel = guild.get_channel(channel_id)

                if user and channel:
                    member_count = len(channel.members)
                    status_emoji = "🌟" if self.is_eligible_creator(user) else "❌"
                    channel_list.append(f"{status_emoji} {user.display_name}: <#{channel_id}> ({member_count}명)")
                else:
                    # Clean up dead references
                    if user_id in system.user_channels:
                        del system.user_channels[user_id]
                    if channel_id in system.channel_owners:
                        del system.channel_owners[channel_id]

            if channel_list:
                embed.add_field(
                    name=f"활성 채널 ({len(channel_list)}개)",
                    value="\n".join(channel_list[:10]) + ("..." if len(channel_list) > 10 else ""),
                    inline=False
                )
            else:
                embed.description = "모든 채널 참조가 정리되었습니다."

        await interaction.followup.send(embed=embed, ephemeral=True)

    @commands.command(name="setup-booster-voice")
    @commands.has_permissions(administrator=True)
    async def setup_booster_voice_command(self, ctx, channel: discord.TextChannel = None):
        """Setup the booster voice channel message with persistent buttons."""

        if channel is None:
            channel = ctx.guild.get_channel(self.booster_channel_id)
            if channel is None:
                await ctx.send("❌ 지정된 채널을 찾을 수 없습니다! 채널을 직접 멘션하거나 설정된 ID가 유효한지 확인하세요.")
                return

        await self._create_booster_message(channel)
        await ctx.send(f"✅ 부스터 음성 채널 메시지가 {channel.mention}에 성공적으로 설정되었습니다!", ephemeral=True)


# Create a view with buttons for easy channel creation
class BoosterVoiceControlView(discord.ui.View):
    """View with buttons for booster voice channel control"""

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="🎤 음성 채널 생성",
        style=discord.ButtonStyle.primary,
        custom_id="create_booster_voice"
    )
    async def create_voice_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        if not self.cog.is_eligible_creator(interaction.user):
            embed = discord.Embed(
                title="❌ 권한 부족",
                description="이 기능은 **서버 부스터** 또는 **특별 역할**을 가진 분만 사용할 수 있습니다.",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        await self.cog.create_booster_channel(interaction.user, interaction)

    @discord.ui.button(
        label="🗑️ 내 채널 삭제",
        style=discord.ButtonStyle.danger,
        custom_id="delete_booster_voice"
    )
    async def delete_voice_channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        system = self.cog.get_system(interaction.guild.id)

        if interaction.user.id not in system.user_channels:
            await interaction.followup.send("삭제할 채널이 없습니다.", ephemeral=True)
            return

        success = await self.cog.delete_booster_channel(interaction.user, "사용자 요청")

        message = "채널이 삭제되었습니다." if success else "삭제 중 오류가 발생했습니다."
        color = discord.Color.green() if success else discord.Color.red()

        embed = discord.Embed(description=message, color=color)
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(BoosterVoiceCog(bot))