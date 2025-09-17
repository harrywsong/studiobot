# cogs/ticket.py - Updated for multi-server support
import asyncio
import discord
from discord.ext import commands
from discord import app_commands, File
from discord.ui import View, Button
from datetime import datetime, timezone
from io import BytesIO
import base64
import html
import traceback

from utils.config import (
    get_channel_id,
    get_role_id,
    is_feature_enabled,
    get_server_setting,
    is_server_configured
)
from utils.logger import get_logger


class HelpView(View):
    def __init__(self, bot, logger_instance):
        super().__init__(timeout=None)
        self.bot = bot
        self.logger = logger_instance

    @discord.ui.button(label="문의하기", style=discord.ButtonStyle.primary, custom_id="open_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: Button):
        # 길드 ID를 로깅을 위한 extra 매개변수에 저장
        guild_id = interaction.guild.id

        # Check server configuration
        if not is_server_configured(guild_id):
            await interaction.response.send_message("❌ 이 서버는 아직 구성되지 않았습니다. 관리자에게 문의하세요.", ephemeral=True)
            return

        if not is_feature_enabled(guild_id, 'ticket_system'):
            await interaction.response.send_message("❌ 이 서버에서는 티켓 시스템이 비활성화되어 있습니다.", ephemeral=True)
            return

        guild = interaction.guild
        member = interaction.user

        # Get ticket category from server config
        ticket_category_id = get_channel_id(guild_id, 'ticket_category')
        if not ticket_category_id:
            # extra={'guild_id': guild_id} 추가
            self.logger.error(f"❌ [ticket] 길드 {guild_id}에 티켓 카테고리가 구성되지 않았습니다.", extra={'guild_id': guild_id})
            await interaction.response.send_message("❌ 티켓 카테고리가 구성되지 않았습니다. 관리자에게 문의해주세요.", ephemeral=True)
            return

        cat = guild.get_channel(ticket_category_id)
        if cat is None:
            # extra={'guild_id': guild_id} 추가
            self.logger.error(f"❌ [ticket] 티켓 카테고리 ID `{ticket_category_id}`를 찾을 수 없습니다.", extra={'guild_id': guild_id})
            await interaction.response.send_message("❌ 티켓 카테고리를 찾을 수 없습니다. 관리자에게 문의해주세요.", ephemeral=True)
            return

        # Get staff role from server config
        staff_role_id = get_role_id(guild_id, 'staff_role')
        if not staff_role_id:
            # extra={'guild_id': guild_id} 추가
            self.logger.error(f"❌ [ticket] 길드 {guild_id}에 스태프 역할이 구성되지 않았습니다.", extra={'guild_id': guild_id})
            await interaction.response.send_message("❌ 스태프 역할이 구성되지 않았습니다. 관리자에게 문의해주세요.", ephemeral=True)
            return

        staff_role = guild.get_role(staff_role_id)
        if staff_role is None:
            # extra={'guild_id': guild_id} 추가
            self.logger.error(f"❌ [ticket] 스태프 역할 ID `{staff_role_id}`를 찾을 수 없습니다.", extra={'guild_id': guild_id})
            await interaction.response.send_message("❌ 스태프 역할을 찾을 수 없어 티켓을 열 수 없습니다. 관리자에게 문의해주세요.", ephemeral=True)
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
            staff_role: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True)
        }

        existing_ticket_channel = discord.utils.get(guild.text_channels, name=f"ticket-{member.id}")
        if existing_ticket_channel:
            await interaction.response.send_message(
                f"❗ 이미 열린 티켓이 있습니다: {existing_ticket_channel.mention}", ephemeral=True
            )
            # extra={'guild_id': guild_id} 추가
            self.logger.info(
                f"❗ {member.display_name} ({member.id})님이 이미 열린 티켓 {existing_ticket_channel.name}을(를) 다시 시도했습니다.",
                extra={'guild_id': guild_id})
            return

        ticket_chan = None
        try:
            ticket_chan = await cat.create_text_channel(f"ticket-{member.id}", overwrites=overwrites,
                                                        reason=f"{member.display_name}님이 티켓 생성")
            await interaction.response.send_message(
                f"✅ 티켓 채널이 생성되었습니다: {ticket_chan.mention}", ephemeral=True
            )
        except discord.Forbidden:
            # extra={'guild_id': guild_id} 추가
            self.logger.error(f"❌ [ticket] {member.display_name} ({member.id})님을 위한 티켓 채널 생성 권한이 없습니다.",
                              extra={'guild_id': guild_id})
            await interaction.response.send_message("❌ 티켓 채널을 생성할 권한이 없습니다. 봇 권한을 확인해주세요.", ephemeral=True)
            return
        except Exception as e:
            # extra={'guild_id': guild_id} 추가
            self.logger.error(f"❌ [ticket] {member.display_name}님을 위한 티켓 채널 생성 실패: {e}\n{traceback.format_exc()}",
                              extra={'guild_id': guild_id})
            await interaction.response.send_message("⚠️ 티켓 채널 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🎫 새 티켓 생성됨",
            description=f"{member.mention}님의 문의입니다.",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="생성자", value=f"{member} (`{member.id}`)", inline=False)
        if ticket_chan:
            embed.add_field(name="티켓 채널", value=ticket_chan.mention, inline=False)
        embed.set_footer(text=f"티켓 ID: {ticket_chan.id}" if ticket_chan else "티켓 생성 실패")

        try:
            await ticket_chan.send(embed=embed, view=CloseTicketView(self.bot, self.logger))
            # extra={'guild_id': guild_id} 추가
            self.logger.info(
                f"🎫 {member.display_name} ({member.id})님이 `{ticket_chan.name}` (ID: {ticket_chan.id}) 티켓을 생성했습니다.",
                extra={'guild_id': guild_id})
        except discord.Forbidden:
            # extra={'guild_id': guild_id} 추가
            self.logger.error(f"❌ [ticket] 티켓 채널 {ticket_chan.name} ({ticket_chan.id})에 메시지를 보낼 권한이 없습니다.",
                              extra={'guild_id': guild_id})
            await interaction.followup.send("⚠️ 티켓 채널에 환영 메시지를 보내는 데 실패했습니다. 봇 권한을 확인해주세요.", ephemeral=True)
        except Exception as e:
            # extra={'guild_id': guild_id} 추가
            self.logger.error(f"❌ [ticket] 티켓 채널에 메시지 전송 실패: {e}\n{traceback.format_exc()}",
                              extra={'guild_id': guild_id})
            await interaction.followup.send("⚠️ 티켓 채널에 메시지를 보내는 데 실패했습니다. 관리자에게 문의해주세요.", ephemeral=True)


class CloseTicketView(View):
    def __init__(self, bot, logger_instance):
        super().__init__(timeout=None)
        self.bot = bot
        self.logger = logger_instance

    @discord.ui.button(label="티켓 닫기", style=discord.ButtonStyle.danger, custom_id="close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: Button):
        # 길드 ID를 로깅을 위한 extra 매개변수에 저장
        guild_id = interaction.guild.id

        try:
            channel = interaction.channel
            if not channel.name.startswith("ticket-"):
                await interaction.response.send_message("❌ 이 채널은 티켓 채널이 아닙니다.", ephemeral=True)
                return

            try:
                owner_id = int(channel.name.split("-", 1)[1])
            except (IndexError, ValueError):
                # extra={'guild_id': guild_id} 추가
                self.logger.error(f"❌ [ticket] 티켓 채널명 '{channel.name}'에서 소유자 ID를 파싱할 수 없습니다.",
                                  extra={'guild_id': guild_id})
                await interaction.response.send_message("❌ 티켓 소유자 정보를 가져오는 데 실패했습니다.", ephemeral=True)
                return

            ticket_owner = channel.guild.get_member(owner_id)
            if ticket_owner is None:
                # extra={'guild_id': guild_id} 추가
                self.logger.warning(f"⚠️ [ticket] 티켓 소유자 ({owner_id})를 찾을 수 없습니다. 이미 서버를 나갔을 수 있습니다.",
                                    extra={'guild_id': guild_id})

            is_owner = interaction.user.id == owner_id

            # Check staff role from server config
            staff_role_id = get_role_id(channel.guild.id, 'staff_role')
            has_sup = False
            if staff_role_id:
                staff_role = channel.guild.get_role(staff_role_id)
                if staff_role:
                    has_sup = staff_role in interaction.user.roles

            is_admin = interaction.user.guild_permissions.administrator

            if not (is_owner or has_sup or is_admin):
                await interaction.response.send_message("❌ 티켓을 닫을 권한이 없습니다.", ephemeral=True)
                # extra={'guild_id': guild_id} 추가
                self.logger.warning(f"🔒 {interaction.user.display_name} ({interaction.user.id})님이 권한 없이 티켓 닫기를 시도했습니다.",
                                    extra={'guild_id': guild_id})
                return

            await interaction.response.defer(ephemeral=True)
            # extra={'guild_id': guild_id} 추가
            self.logger.info(
                f"⏳ {interaction.user.display_name} ({interaction.user.id})님이 티켓 {channel.name}을(를) 닫는 중입니다.",
                extra={'guild_id': guild_id})
            await interaction.followup.send("⏳ 티켓을 닫는 중입니다...", ephemeral=True)

            created_ts = channel.created_at.strftime("%Y-%m-%d %H:%M UTC")

            all_msgs = []
            async for m in channel.history(limit=200, oldest_first=True):
                all_msgs.append(m)

            msgs = [m for m in all_msgs if not (m.author == self.bot.user and m.reference is None and not m.content)]

            css = """
            @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@400;700&display=swap');

            body {
              margin: 0;
              padding: 30px 15px;
              background: #f9fafb;
              color: #2e2e2e;
              font-family: 'Roboto', sans-serif;
            }

            .container {
              max-width: 900px;
              margin: 0 auto;
              background: #ffffff;
              border-radius: 16px;
              box-shadow: 0 12px 24px rgba(0,0,0,0.1);
              padding: 40px 30px;
            }

            .header {
              text-align: center;
              margin-bottom: 40px;
            }

            .header h1 {
              margin: 0;
              color: #3b82f6;
              font-size: 2.75rem;
              font-weight: 700;
              letter-spacing: -0.02em;
            }

            .header .meta {
              font-size: 1rem;
              color: #6b7280;
              margin-top: 10px;
              font-weight: 400;
            }

            .messages {
              display: flex;
              flex-direction: column;
              gap: 28px;
            }

            .msg {
              display: flex;
              gap: 20px;
              align-items: flex-start;
              background: #f3f4f6;
              border-radius: 14px;
              padding: 16px 20px;
              box-shadow: 0 4px 8px rgba(59,130,246,0.1);
              transition: background-color 0.2s ease;
            }

            .msg:hover {
              background-color: #e0e7ff;
            }

            .avatar {
              width: 50px;
              height: 50px;
              border-radius: 50%;
              flex-shrink: 0;
              box-shadow: 0 2px 8px rgba(59,130,246,0.2);
            }

            .username {
              font-weight: 700;
              font-size: 1.1rem;
              color: #1e40af;
              display: inline-block;
            }

            .timestamp {
              font-size: 0.8rem;
              color: #9ca3af;
              margin-left: 14px;
              font-weight: 500;
            }

            .text {
              margin-top: 8px;
              font-size: 1rem;
              line-height: 1.55;
              white-space: pre-wrap;
              color: #374151;
            }

            img.attachment {
              max-width: 100%;
              border-radius: 14px;
              margin-top: 16px;
              box-shadow: 0 8px 20px rgba(59,130,246,0.1);
              border: 1px solid #d1d5db;
            }

            .footer {
              text-align: center;
              margin-top: 50px;
              font-size: 0.9rem;
              color: #6b7280;
              font-weight: 400;
            }
            """

            messages_html = ""
            for m in msgs:
                when = m.created_at.strftime("%Y-%m-%d %H:%M UTC")
                name = html.escape(m.author.display_name)
                content = html.escape(m.content or "")
                avatar_url = m.author.display_avatar.url
                content = discord.utils.remove_markdown(content)
                content = content.replace('\n', '<br>')

                messages_html += f"""
    <div class="msg">
      <img class="avatar" src="{avatar_url}" alt="avatar">
      <div class="bubble">
        <span class="username">{name}</span>
        <span class="timestamp">{when}</span>
        <div class="text">{content}</div>
    """

                for att in m.attachments:
                    try:
                        if att.content_type and att.content_type.startswith("image/"):
                            b64 = base64.b64encode(await att.read()).decode("ascii")
                            ctype = att.content_type
                            messages_html += f"""
            <img class="attachment" src="data:{ctype};base64,{b64}" alt="{html.escape(att.filename)}">
        """
                        else:
                            messages_html += f"""
            <div class="attachment-link"><a href="{att.url}" target="_blank">{html.escape(att.filename)}</a></div>
        """
                    except Exception as att_e:
                        # extra={'guild_id': guild_id} 추가
                        self.logger.warning(f"⚠️ [ticket] 첨부 파일 '{att.filename}' 처리 실패: {att_e}",
                                            extra={'guild_id': guild_id})

                messages_html += "  </div>\n</div>"

            now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            html_doc = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8">
      <title>Ticket Transcript for {channel.name}</title>
      <style>{css}</style>
    </head>
    <body>
      <div class="container">
        <div class="header">
          <h1>Transcript for {channel.name}</h1>
          <p class="meta">Created: {created_ts} • Owner: {ticket_owner.display_name if ticket_owner else "Unknown User"}</p>
        </div>
        <div class="messages">
          {messages_html}
        </div>
        <div class="footer">Generated by {self.bot.user.name} on {now_utc}</div>
      </div>
    </body>
    </html>
    """.strip()

            buf = BytesIO(html_doc.encode("utf-8"))
            buf.seek(0)

            close_embed = discord.Embed(
                title="🎫 티켓 닫힘",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc)
            )
            close_embed.add_field(name="티켓 채널", value=channel.name, inline=False)
            close_embed.add_field(name="티켓 소유자", value=str(ticket_owner) if ticket_owner else "알 수 없음", inline=False)
            close_embed.add_field(name="닫은 사람", value=str(interaction.user), inline=False)
            close_embed.set_footer(text=f"티켓 ID: {channel.id}")

            # Get history channel from server config
            history_channel_id = get_channel_id(channel.guild.id, 'ticket_history_channel')
            if history_channel_id:
                history_ch = channel.guild.get_channel(history_channel_id)
                if history_ch:
                    await history_ch.send(embed=close_embed, file=File(buf,
                                                                       filename=f"{channel.name}-{datetime.now().strftime('%Y%m%d%H%M%S')}.html"))
                    # extra={'guild_id': guild_id} 추가
                    self.logger.info(
                        f"✅ {ticket_owner.display_name if ticket_owner else '알 수 없는 사용자'}님의 `{channel.name}` (ID: {channel.id}) 티켓이 닫히고 기록이 저장되었습니다.",
                        extra={'guild_id': guild_id})
                else:
                    # extra={'guild_id': guild_id} 추가
                    self.logger.warning(f"⚠️ HISTORY 채널 ID `{history_channel_id}`를 찾을 수 없어 티켓 기록을 저장할 수 없습니다.",
                                        extra={'guild_id': guild_id})
                    await interaction.followup.send("⚠️ 기록 채널을 찾을 수 없어 티켓 기록을 저장하지 못했습니다.", ephemeral=True)
            else:
                # extra={'guild_id': guild_id} 추가
                self.logger.warning(f"⚠️ 길드 {channel.guild.id}에 HISTORY 채널이 구성되지 않아 티켓 기록을 저장할 수 없습니다.",
                                    extra={'guild_id': guild_id})
                await interaction.followup.send("⚠️ 기록 채널이 구성되지 않아 티켓 기록을 저장하지 못했습니다.", ephemeral=True)

            try:
                await channel.send("이 티켓은 잠시 후 삭제됩니다. 필요하다면 위의 기록을 확인해주세요.")
            except discord.Forbidden:
                # extra={'guild_id': guild_id} 추가
                self.logger.warning(f"⚠️ 티켓 채널 {channel.name}에 삭제 전 메시지를 보낼 권한이 없습니다.", extra={'guild_id': guild_id})

            await asyncio.sleep(5)

            await channel.delete(reason=f"티켓 종료: {interaction.user.display_name}")
            # extra={'guild_id': guild_id} 추가
            self.logger.info(f"🗑️ 티켓 채널 '{channel.name}' (ID: {channel.id})이(가) 삭제되었습니다.", extra={'guild_id': guild_id})

        except Exception as e:
            # extra={'guild_id': guild_id} 추가
            self.logger.error(f"❌ [ticket] 티켓 종료 중 오류 발생: {e}\n{traceback.format_exc()}", extra={'guild_id': guild_id})
            if not interaction.response.is_done():
                try:
                    await interaction.followup.send("❌ 티켓 닫기 중 오류가 발생했습니다. 관리자에게 문의해주세요.", ephemeral=True)
                except discord.InteractionResponded:
                    pass


class TicketSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # NOTE: Arguments here will be ignored by get_logger due to global configuration,
        # but the line is kept for clarity.
        self.logger = get_logger("티켓 시스템")
        self.logger.info("티켓 시스템 기능이 초기화되었습니다.")

    async def send_ticket_request_message(self, guild_id: int):
        """Send ticket request message for a specific guild"""
        # 길드 ID는 이미 매개변수로 전달되므로, extra에 추가만 하면 됩니다.
        if not is_feature_enabled(guild_id, 'ticket_system'):
            return

        ticket_channel_id = get_channel_id(guild_id, 'ticket_channel')
        if not ticket_channel_id:
            # extra={'guild_id': guild_id} 추가
            self.logger.warning(f"길드 {guild_id}에 티켓 채널이 구성되지 않았습니다.", extra={'guild_id': guild_id})
            return

        channel = self.bot.get_channel(ticket_channel_id)
        if channel is None:
            # extra={'guild_id': guild_id} 추가
            self.logger.error(f"❌ 길드 {guild_id}의 티켓 요청 메시지를 보낼 채널 (ID: {ticket_channel_id})을(를) 찾을 수 없습니다!",
                              extra={'guild_id': guild_id})
            return

        try:
            async for msg in channel.history(limit=5):
                if msg.author == self.bot.user and msg.embeds:
                    if any("✨ 티켓 생성하기 ✨" in embed.title for embed in msg.embeds):
                        await msg.delete()
                        # extra={'guild_id': guild_id} 추가
                        self.logger.info(f"이전 티켓 요청 메시지 삭제됨 (ID: {msg.id})", extra={'guild_id': guild_id})
                        break
            else:
                # extra={'guild_id': guild_id} 추가
                self.logger.debug(f"채널 {channel.name}에 기존 티켓 요청 메시지가 없습니다.", extra={'guild_id': guild_id})

        except discord.Forbidden:
            # extra={'guild_id': guild_id} 추가
            self.logger.error(f"❌ {channel.name} 채널 ({channel.id})의 메시지 삭제 권한이 없습니다. 봇 권한을 확인해주세요.",
                              extra={'guild_id': guild_id})
        except Exception as e:
            # extra={'guild_id': guild_id} 추가
            self.logger.error(f"❌ {channel.name} 채널의 메시지 삭제 실패: {e}\n{traceback.format_exc()}",
                              extra={'guild_id': guild_id})

        embed = discord.Embed(
            title="✨ 티켓 생성하기 ✨",
            description=(
                "서버 이용 중 불편하시거나 개선 제안이 있으신가요?\n"
                "아래 버튼을 눌러 문의 티켓을 열어주세요.\n"
                "운영진이 빠르게 확인하고 도움을 드리겠습니다."
            ),
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_thumbnail(
            url="https://cdn1.iconfinder.com/data/icons/unicons-line-vol-2/24/comment-question-256.png"
        )
        embed.set_footer(text="아날로그 • 티켓 시스템")
        embed.set_author(
            name="티켓 안내",
            icon_url="https://cdn-icons-png.flaticon.com/512/295/295128.png"
        )

        try:
            await channel.send(embed=embed, view=HelpView(self.bot, self.logger))
            # extra={'guild_id': guild_id} 추가
            self.logger.info(f"✅ {channel.name} ({channel.id}) 채널에 문의 요청 메시지를 성공적으로 보냈습니다.",
                             extra={'guild_id': guild_id})
        except discord.Forbidden:
            # extra={'guild_id': guild_id} 추가
            self.logger.error(f"❌ 문의 요청 메시지를 보낼 권한이 없습니다 (채널 {channel.id}). 봇 권한을 확인해주세요.",
                              extra={'guild_id': guild_id})
        except Exception as e:
            # extra={'guild_id': guild_id} 추가
            self.logger.error(f"❌ 문의 요청 메시지 전송에 실패했습니다: {e}\n{traceback.format_exc()}", extra={'guild_id': guild_id})

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(HelpView(self.bot, self.logger))
        self.bot.add_view(CloseTicketView(self.bot, self.logger))

        # 일반적인 초기화 로그이므로 extra 매개변수가 필요하지 않습니다.
        self.logger.info("지속적인 뷰(HelpView, CloseTicketView)가 등록되었습니다.")

        await asyncio.sleep(2)

        # Send ticket request messages for all configured guilds
        for guild in self.bot.guilds:
            if is_server_configured(guild.id) and is_feature_enabled(guild.id, 'ticket_system'):
                # send_ticket_request_message 함수가 이미 guild.id를 처리합니다.
                await self.send_ticket_request_message(guild.id)

    @app_commands.command(name="help", description="운영진에게 문의할 수 있는 티켓을 엽니다.")
    async def slash_help(self, interaction: discord.Interaction):
        # 길드 ID를 로깅을 위한 extra 매개변수에 저장
        guild_id = interaction.guild.id

        # Check server configuration
        if not is_server_configured(guild_id):
            await interaction.response.send_message("❌ 이 서버는 아직 구성되지 않았습니다. `/봇설정` 명령어를 사용하여 설정해주세요.", ephemeral=True)
            return

        if not is_feature_enabled(guild_id, 'ticket_system'):
            await interaction.response.send_message("❌ 이 서버에서는 티켓 시스템이 비활성화되어 있습니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        embed = discord.Embed(
            title="문의 사항이 있으신가요?",
            description=(
                "아래 '문의하기' 버튼을 눌러주세요.\n"
                "개별 티켓 채널이 생성되어 운영진이 도움을 드립니다."
            ),
            color=discord.Color.teal()
        )
        embed.set_footer(text="아날로그 • 티켓 시스템")
        try:
            await interaction.followup.send(embed=embed, view=HelpView(self.bot, self.logger), ephemeral=True)
            # extra={'guild_id': guild_id} 추가
            self.logger.info(f"👤 {interaction.user.display_name} ({interaction.user.id})님이 /help 명령어를 사용했습니다.",
                             extra={'guild_id': guild_id})
        except Exception as e:
            # extra={'guild_id': guild_id} 추가
            self.logger.error(f"❌ /help 명령어 응답 실패: {e}\n{traceback.format_exc()}", extra={'guild_id': guild_id})
            await interaction.followup.send("❌ 도움말 메시지를 보내는 데 실패했습니다. 잠시 후 다시 시도해주세요.", ephemeral=True)

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        """Handle bot joining a new guild"""
        # 길드 ID를 로깅을 위한 extra 매개변수에 추가
        self.logger.info(f"Bot joined new guild for tickets: {guild.name} ({guild.id})", extra={'guild_id': guild.id})

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        """Handle bot leaving a guild"""
        # 길드 ID를 로깅을 위한 extra 매개변수에 추가
        self.logger.info(f"Bot left guild for tickets: {guild.name} ({guild.id})", extra={'guild_id': guild.id})


async def setup(bot):
    await bot.add_cog(TicketSystem(bot))