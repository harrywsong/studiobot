import discord
from discord.ext import commands
from discord import app_commands
import re
import asyncio
from datetime import datetime, timedelta
import json
import os
from utils.config import get_role_id, load_server_config


class PersistentColorView(discord.ui.View):
    """Persistent view for color selection button that doesn't expire."""

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label='🎨 색상 변경하기',
        style=discord.ButtonStyle.primary,
        custom_id='persistent_color_button'
    )
    async def color_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle the persistent color button click."""

        # Check if user is a booster
        if not self.cog.is_server_booster(interaction.user):
            embed = discord.Embed(
                title="🚫 프리미엄 기능",
                description="이 기능은 **서버 부스터** 전용입니다!\n\n이 서버를 부스트하여 사용자 지정 색상 및 기타 특혜를 잠금 해제하세요.",
                color=0xFF5733
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Check cooldown (24 hours)
        user_id = interaction.user.id
        if user_id in self.cog.color_cooldowns:
            last_change = datetime.fromtimestamp(self.cog.color_cooldowns[user_id])
            cooldown_end = last_change + timedelta(hours=24)

            if datetime.now() < cooldown_end:
                time_left = cooldown_end - datetime.now()
                hours = int(time_left.total_seconds() // 3600)
                minutes = int((time_left.total_seconds() % 3600) // 60)

                embed = discord.Embed(
                    title="⏰ 쿨다운 중",
                    description=f"**{hours}시간 {minutes}분** 후에 다시 색상을 변경할 수 있습니다.",
                    color=0xFFAA00
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

        # Show color modal
        modal = self.cog.ColorModal(self.cog)
        await interaction.response.send_modal(modal)


class BoosterPerks(commands.Cog):
    """서버 부스터 전용 특혜 및 기능."""

    def __init__(self, bot):
        self.bot = bot
        self.color_cooldowns = {}
        self.booster_message_id = None  # Track the booster message
        self.booster_channel_id = 1366767855462518825  # Your specified channel
        self.betting_limits = {
            'normal': 200,
            'booster': 500
        }

        # 지속적인 데이터 로드
        self.data_file = 'booster_data.json'
        self.load_data()

        # Add persistent view
        self.persistent_view = PersistentColorView(self)

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
            guild = self.bot.get_guild(1059211805567746090)  # Your guild ID from config
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
                    # Verify it has the correct embed and view
                    if message.embeds and message.embeds[0].title == "🌟 서버 부스터 특별 혜택":
                        message_exists = True
                    else:
                        # Message exists but wrong content, delete it
                        await message.delete()
                        message_exists = False
                except discord.NotFound:
                    message_exists = False
                except discord.Forbidden:
                    return  # Can't manage messages

            # Recreate message if missing or invalid
            if not message_exists:
                await self._create_booster_message(channel)

        except Exception as e:
            print(f"Error validating booster message: {e}")

    async def _create_booster_message(self, channel):
        """Create the booster message embed and view."""
        embed = discord.Embed(
            title="🌟 서버 부스터 특별 혜택",
            description="서버를 부스트해주신 분들을 위한 독점적인 특혜를 소개합니다!",
            color=0xFF73FA
        )

        embed.add_field(
            name="🎨 사용자 지정 이름 색상",
            value=(
                "• 아래 버튼을 클릭하여 원하는 색상을 선택하세요\n"
                "• 헥스 코드 형식으로 입력 (예: #FF5733)\n"
                "• 24시간마다 한 번씩 변경 가능\n"
                "• 스태프 역할과 충돌하지 않는 색상만 허용"
            ),
            inline=False
        )

        embed.add_field(
            name="💰 향상된 게임 한도",
            value=(
                "• **베팅 한도**: 500 코인 (일반 회원: 200)\n"
                "• **우선 지원**: 빠른 문의 응답"
            ),
            inline=False
        )

        embed.add_field(
            name="📋 사용 방법",
            value=(
                "1️⃣ 아래 **🎨 색상 변경하기** 버튼 클릭\n"
                "2️⃣ 팝업 창에 원하는 헥스 색상 코드 입력\n"
                "3️⃣ 제출하면 자동으로 색상 역할이 생성됩니다\n"
                "4️⃣ 24시간 후 다시 변경 가능합니다"
            ),
            inline=False
        )

        embed.add_field(
            name="⚠️ 주의사항",
            value=(
                "• 유효한 헥스 코드만 사용 가능 (#FF5733 형식)\n"
                "• 스태프 색상과 동일한 색상은 금지\n"
                "• 부스터 상태를 잃으면 색상 역할이 자동 제거됩니다\n"
                "• 악용 시 특혜가 제한될 수 있습니다"
            ),
            inline=False
        )

        try:
            guild = channel.guild
            embed.set_footer(
                text="이 서버를 부스트해주셔서 감사합니다! • 문의사항은 스태프에게 연락하세요",
                icon_url=guild.icon.url if guild.icon else None
            )
        except:
            embed.set_footer(text="이 서버를 부스트해주셔서 감사합니다! • 문의사항은 스태프에게 연락하세요")

        try:
            message = await channel.send(embed=embed, view=self.persistent_view)
            self.booster_message_id = message.id
            self.save_data()
            print(f"✅ Booster message created/recreated in {channel.name}")
        except discord.Forbidden:
            print(f"❌ No permission to send messages in {channel.name}")
        except Exception as e:
            print(f"❌ Error creating booster message: {e}")

    def load_data(self):
        """지속적인 부스터 데이터 로드."""
        try:
            with open(self.data_file, 'r') as f:
                data = json.load(f)
                self.color_cooldowns = data.get('color_cooldowns', {})
                self.booster_message_id = data.get('booster_message_id', None)
        except FileNotFoundError:
            self.color_cooldowns = {}
            self.booster_message_id = None

    def save_data(self):
        """지속적인 부스터 데이터 저장."""
        data = {
            'color_cooldowns': self.color_cooldowns,
            'booster_message_id': self.booster_message_id
        }
        with open(self.data_file, 'w') as f:
            json.dump(data, f)

    def is_server_booster(self, member: discord.Member) -> bool:
        """멤버가 서버 부스터인지 확인."""
        # Staff role with ID 1417771791384051823 is granted booster privileges.
        staff_booster_role_id = 1417771791384051823
        staff_role = member.guild.get_role(staff_booster_role_id)
        if staff_role and staff_role in member.roles:
            return True

        # 방법 1: 프리미엄 상태 확인 (디스코드 내장 부스팅)
        if member.premium_since is not None:
            return True

        # 방법 2: 서버 설정에서 지정된 부스터 역할 확인 (config.py 사용)
        custom_booster_role_id = get_role_id(member.guild.id, 'booster_role')
        if custom_booster_role_id:
            custom_booster_role = member.guild.get_role(custom_booster_role_id)
            if custom_booster_role and custom_booster_role in member.roles:
                return True

        # 방법 3: 디스코드의 기본 부스터 역할 확인
        booster_role = discord.utils.get(member.guild.roles, name="Server Booster")
        if booster_role and booster_role in member.roles:
            return True

        # 방법 4: 기타 일반적인 부스터 역할 이름 확인
        booster_role_names = ["Nitro Booster", "Booster", "Premium Member"]
        for role in member.roles:
            if role.name in booster_role_names:
                return True

        return False

    def validate_hex_color(self, hex_color: str) -> bool:
        """헥스 색상 형식을 유효성 검사."""
        if not hex_color.startswith('#'):
            hex_color = '#' + hex_color

        pattern = r'^#[0-9A-Fa-f]{6}$'
        return bool(re.match(pattern, hex_color))

    def is_forbidden_color(self, hex_color: str, guild: discord.Guild) -> bool:
        """중요한 역할과 색상이 충돌하는지 확인."""
        forbidden_role_names = ['Admin', 'Moderator', 'Staff', 'Bot', '토토로']
        color_int = int(hex_color.lstrip('#'), 16)

        for role in guild.roles:
            if any(name.lower() in role.name.lower() for name in forbidden_role_names):
                if role.color.value == color_int:
                    return True
        return False

    async def cleanup_old_color_role(self, member: discord.Member):
        """멤버의 이전 색상 역할을 제거하고 사용되지 않으면 삭제."""
        for role in member.roles:
            if role.name.startswith('🎨 ') and not role.managed:
                await member.remove_roles(role, reason="이전 색상 역할 제거")

                # 다른 멤버가 사용하지 않으면 역할 삭제
                if len(role.members) == 0:
                    try:
                        await role.delete(reason="사용되지 않는 색상 역할 정리")
                    except discord.Forbidden:
                        pass
                break

    async def create_color_role(self, member: discord.Member, hex_color: str) -> discord.Role:
        """멤버를 위한 새로운 색상 역할 생성."""
        guild = member.guild

        # 이전 역할 먼저 정리
        await self.cleanup_old_color_role(member)

        # 새 역할 생성
        color_int = int(hex_color.lstrip('#'), 16)
        role_name = f"🎨 {member.display_name}"

        color_role = await guild.create_role(
            name=role_name,
            color=discord.Color(color_int),
            permissions=discord.Permissions.none(),
            mentionable=False,
            reason=f"부스터 {member}를 위한 사용자 지정 색상"
        )

        # 역할을 올바른 위치에 배치
        target_position = self._calculate_color_role_position(guild)

        try:
            await color_role.edit(position=target_position)
        except discord.Forbidden:
            pass  # 봇에게 역할 순서 변경 권한이 없을 수 있음
        except discord.HTTPException:
            pass  # 위치가 유효하지 않을 수 있음

        # 멤버에게 역할 할당
        await member.add_roles(color_role, reason="사용자 지정 색상 적용")

        return color_role

    def _calculate_color_role_position(self, guild: discord.Guild) -> int:
        """역할 계층에서 색상 역할의 이상적인 위치 계산."""

        # 1차 전략: 특정 대상 역할 (ID: 1366087688263827477) 사용
        # 모든 색상 역할은 이 역할 바로 아래에 위치해야 함
        target_role_id = 1366087688263827477
        target_role = guild.get_role(target_role_id)

        if target_role:
            # 색상 역할을 대상 역할 바로 아래에 배치
            target_position = max(1, target_role.position - 1)
            return target_position

        # 대체 전략: config에서 멤버 역할 찾기
        try:
            from utils.config import get_role_id
            member_role_id = get_role_id(guild.id, 'member_role')
            if member_role_id:
                member_role = guild.get_role(member_role_id)
                if member_role:
                    # 색상 역할은 멤버 역할 ABOVE에 배치되어야 색상이 표시됨
                    return max(1, member_role.position + 1)
        except ImportError:
            pass

        # 2차 대체 전략: 일반적인 멤버 역할들을 찾아 그 위에 배치
        member_roles = [
            "UofT",
            "Server Booster",
            "Nitro Booster",
            "member",
            "Member",
            "verified",
            "Verified",
            "정령"  # From your config
        ]

        highest_member_role_position = 1

        for role in guild.roles:
            # 관리되는 역할 (봇, 통합 등) 건너뛰기
            if role.managed:
                continue

            # 멤버 유형 역할인지 확인
            role_name_lower = role.name.lower()
            if any(member_name.lower() in role_name_lower for member_name in member_roles):
                highest_member_role_position = max(highest_member_role_position, role.position)

        # 색상 역할을 가장 높은 멤버 역할 ABOVE에 배치 (색상이 보이도록)
        target_position = highest_member_role_position + 1

        # 서버의 최대 역할 수를 초과하지 않도록 제한
        return min(target_position, len(guild.roles))

    class ColorModal(discord.ui.Modal):
        def __init__(self, cog):
            super().__init__(title="🎨 색상 선택")
            self.cog = cog

            self.color_input = discord.ui.TextInput(
                label="헥스 색상 코드",
                placeholder="#FF5733 또는 FF5733",
                required=True,
                max_length=7,
                min_length=6
            )
            self.add_item(self.color_input)

        async def on_submit(self, interaction: discord.Interaction):
            hex_color = self.color_input.value.strip()

            # #이 없으면 추가
            if not hex_color.startswith('#'):
                hex_color = '#' + hex_color

            # 색상 유효성 검사
            if not self.cog.validate_hex_color(hex_color):
                await interaction.response.send_message(
                    "❌ 유효하지 않은 헥스 색상 형식입니다! `#FF5733` 형식으로 사용해주세요.",
                    ephemeral=True
                )
                return

            # 금지된 색상 확인
            if self.cog.is_forbidden_color(hex_color, interaction.guild):
                await interaction.response.send_message(
                    "❌ 이 색상은 스태프 역할을 위해 예약되어 있습니다!",
                    ephemeral=True
                )
                return

            try:
                await interaction.response.defer(ephemeral=True)

                color_role = await self.cog.create_color_role(interaction.user, hex_color)

                # 쿨다운 설정
                self.cog.color_cooldowns[interaction.user.id] = datetime.now().timestamp()
                self.cog.save_data()

                embed = discord.Embed(
                    title="✅ 색상 변경 완료!",
                    description=f"색상이 `{hex_color.upper()}`로 설정되었습니다.",
                    color=int(hex_color.lstrip('#'), 16)
                )
                embed.set_footer(text="24시간 후에 다시 색상을 변경할 수 있습니다.")

                await interaction.followup.send(embed=embed, ephemeral=True)

            except discord.Forbidden:
                await interaction.followup.send(
                    "❌ 역할 생성 권한이 없습니다!",
                    ephemeral=True
                )
            except Exception as e:
                await interaction.followup.send(
                    f"❌ 오류가 발생했습니다: {str(e)}",
                    ephemeral=True
                )

    @commands.command(name="setup-booster-channel")
    @commands.has_permissions(administrator=True)
    async def setup_booster_channel(self, ctx, channel: discord.TextChannel = None):
        """Setup the booster channel with persistent color selection."""

        if channel is None:
            # Use the specific channel ID you provided
            channel = ctx.guild.get_channel(1366767855462518825)
            if channel is None:
                await ctx.send("❌ 지정된 채널을 찾을 수 없습니다!")
                return

        # Create the informational embed
        embed = discord.Embed(
            title="🌟 서버 부스터 특별 혜택",
            description="서버를 부스트해주신 분들을 위한 독점적인 특혜를 소개합니다!",
            color=0xFF73FA
        )

        embed.add_field(
            name="🎨 사용자 지정 이름 색상",
            value=(
                "• 아래 버튼을 클릭하여 원하는 색상을 선택하세요\n"
                "• 헥스 코드 형식으로 입력 (예: #FF5733)\n"
                "• 24시간마다 한 번씩 변경 가능\n"
                "• 스태프 역할과 충돌하지 않는 색상만 허용"
            ),
            inline=False
        )

        embed.add_field(
            name="💰 향상된 게임 한도",
            value=(
                "• **베팅 한도**: 5,000 코인 (일반 회원: 1,000)\n"
                "• **우선 지원**: 빠른 문의 응답"
            ),
            inline=False
        )

        embed.add_field(
            name="📋 사용 방법",
            value=(
                "1️⃣ 아래 **🎨 색상 변경하기** 버튼 클릭\n"
                "2️⃣ 팝업 창에 원하는 헥스 색상 코드 입력\n"
                "3️⃣ 제출하면 자동으로 색상 역할이 생성됩니다\n"
                "4️⃣ 24시간 후 다시 변경 가능합니다"
            ),
            inline=False
        )

        embed.add_field(
            name="⚠️ 주의사항",
            value=(
                "• 유효한 헥스 코드만 사용 가능 (#FF5733 형식)\n"
                "• 스태프 색상과 동일한 색상은 금지\n"
                "• 부스터 상태를 잃으면 색상 역할이 자동 제거됩니다\n"
                "• 악용 시 특혜가 제한될 수 있습니다"
            ),
            inline=False
        )

        embed.set_footer(
            text="이 서버를 부스트해주셔서 감사합니다! • 문의사항은 스태프에게 연락하세요",
            icon_url=ctx.guild.icon.url if ctx.guild.icon else None
        )

        embed.set_thumbnail(url="https://cdn.discordapp.com/emojis/852881418382819348.png")  # Boost emoji

        # Send the embed with persistent view
        try:
            message = await channel.send(embed=embed, view=self.persistent_view)
            # Store the message ID for tracking
            self.booster_message_id = message.id
            self.save_data()
            await ctx.send(f"✅ 부스터 채널이 {channel.mention}에 성공적으로 설정되었습니다!")
        except discord.Forbidden:
            await ctx.send("❌ 해당 채널에 메시지를 보낼 권한이 없습니다!")
        except Exception as e:
            await ctx.send(f"❌ 오류가 발생했습니다: {str(e)}")

    # ... (rest of the existing methods remain the same)
    @app_commands.command(name="color", description="이름 색상 변경 (서버 부스터 전용)")
    async def color_command(self, interaction: discord.Interaction):
        """이름 색상 변경 - 서버 부스터 전용."""

        # 사용자가 부스터인지 확인
        if not self.is_server_booster(interaction.user):
            embed = discord.Embed(
                title="🚫 프리미엄 기능",
                description="이 기능은 **서버 부스터** 전용입니다!\n\n이 서버를 부스트하여 사용자 지정 색상 및 기타 특혜를 잠금 해제하세요.",
                color=0xFF5733
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # 쿨다운 확인 (24시간)
        user_id = interaction.user.id
        if user_id in self.color_cooldowns:
            last_change = datetime.fromtimestamp(self.color_cooldowns[user_id])
            cooldown_end = last_change + timedelta(hours=24)

            if datetime.now() < cooldown_end:
                time_left = cooldown_end - datetime.now()
                hours = int(time_left.total_seconds() // 3600)
                minutes = int((time_left.total_seconds() % 3600) // 60)

                embed = discord.Embed(
                    title="⏰ 쿨다운 중",
                    description=f"**{hours}시간 {minutes}분** 후에 다시 색상을 변경할 수 있습니다.",
                    color=0xFFAA00
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

        # 색상 선택 모달 표시
        modal = self.ColorModal(self)
        await interaction.response.send_modal(modal)

    @app_commands.command(name="remove-color", description="사용자 지정 색상 역할 제거")
    async def remove_color(self, interaction: discord.Interaction):
        """사용자 지정 색상 역할 제거."""

        if not self.is_server_booster(interaction.user):
            await interaction.response.send_message(
                "❌ 서버 부스터만 사용자 지정 색상을 관리할 수 있습니다!",
                ephemeral=True
            )
            return

        await self.cleanup_old_color_role(interaction.user)

        embed = discord.Embed(
            title="✅ 색상 제거됨",
            description="사용자 지정 색상 역할이 제거되었습니다.",
            color=0x00FF00
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    def get_betting_limit(self, member: discord.Member) -> int:
        """부스터 상태에 따라 멤버의 베팅 한도 가져오기."""
        if self.is_server_booster(member):
            return self.betting_limits['booster']
        return self.betting_limits['normal']

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """부스터 상태 변경 처리."""

        # 멤버가 부스터 상태를 잃었는지 확인
        if before.premium_since and not after.premium_since:
            # 부스터 상태를 잃었을 때 색상 역할 제거
            await self.cleanup_old_color_role(after)

            # 알림 보내기 (선택 사항)
            try:
                embed = discord.Embed(
                    title="💔 부스터 상태 상실",
                    description="서버 부스트를 더 이상 하지 않아 사용자 지정 색상 역할이 제거되었습니다.\n\n언제든지 다시 부스트하여 모든 특혜를 되찾으세요!",
                    color=0xFF4444
                )
                await after.send(embed=embed)
            except discord.Forbidden:
                pass  # 사용자가 DM을 비활성화했을 수 있음

    @commands.command(name="cleanup-colors")
    @commands.has_permissions(administrator=True)
    async def cleanup_colors(self, ctx):
        """사용되지 않는 색상 역할을 정리하는 관리자 명령어."""

        deleted_count = 0

        for role in ctx.guild.roles:
            if role.name.startswith('🎨 ') and not role.managed and len(role.members) == 0:
                try:
                    await role.delete(reason="색상 역할 정리")
                    deleted_count += 1
                except discord.Forbidden:
                    pass

        embed = discord.Embed(
            title="🧹 정리 완료",
            description=f"사용되지 않는 색상 역할 **{deleted_count}개**가 제거되었습니다.",
            color=0x00FF00
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(BoosterPerks(bot))