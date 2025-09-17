# cogs/achievements.py - Fixed for proper multi-server support with hint system
import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
from collections import defaultdict
import datetime
from datetime import timedelta, time as dt_time
import asyncio
import traceback
from typing import Optional
import pytz
import re

# Updated imports for multi-server config
from utils.config import (
    ACHIEVEMENT_DATA_PATH,
    HOLIDAYS,
    ACHIEVEMENT_EMOJIS,
    get_channel_id,
    get_role_id,
    is_feature_enabled,
    is_server_configured,
    get_server_setting,
    get_all_server_configs
)
from utils.logger import get_logger


class PersistentAchievementView(discord.ui.View):
    def __init__(self, bot, guild_id, members=None):
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = guild_id
        self.logger = get_logger("업적 시스템")
        self.current_page = 0
        self.members = members
        self.max_pages = len(self.members) - 1 if self.members else 0
        self.update_buttons()

    async def _get_data(self):
        cog = self.bot.get_cog("Achievements")
        if not cog:
            self.logger.error("PersistentAchievementView: Achievements cog not found",
                              extra={'guild_id': self.guild_id})
            return None, None

        if not self.members:
            self.members = await cog._get_sorted_members(self.guild_id)

        self.max_pages = len(self.members) - 1 if self.members else 0
        self.update_buttons()
        return cog, self.members

    def update_buttons(self):
        self.first.disabled = self.current_page == 0
        self.prev_5.disabled = self.current_page == 0
        self.prev.disabled = self.current_page == 0
        self.next.disabled = self.current_page == self.max_pages
        self.next_5.disabled = self.current_page == self.max_pages
        self.last.disabled = self.current_page == self.max_pages

    async def get_current_embed(self, cog, members):
        if not members:
            return discord.Embed(description="No members found with achievements.")

        current_member = members[self.current_page]
        return await cog._create_achievements_embed(current_member, self.current_page + 1, self.max_pages + 1)

    async def update_response(self, interaction: discord.Interaction):
        cog, members = await self._get_data()
        if not cog or not members:
            await interaction.response.edit_message(content="An error occurred while fetching achievement data.",
                                                    view=None)
            return

        embed = await self.get_current_embed(cog, members)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="« 처음", style=discord.ButtonStyle.blurple, custom_id="persistent_first_page_button")
    async def first(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = 0
        await self.update_response(interaction)

    @discord.ui.button(label="« 5", style=discord.ButtonStyle.secondary, custom_id="persistent_prev_5_button")
    async def prev_5(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = max(0, self.current_page - 5)
        await self.update_response(interaction)

    @discord.ui.button(label="‹ 뒤로", style=discord.ButtonStyle.secondary, custom_id="persistent_prev_page_button")
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = max(0, self.current_page - 1)
        await self.update_response(interaction)

    @discord.ui.button(label="다음 ›", style=discord.ButtonStyle.secondary, custom_id="persistent_next_page_button")
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog, members = await self._get_data()
        if not members:
            await interaction.response.edit_message(content="An error occurred while fetching achievement data.",
                                                    view=None)
            return
        self.current_page = min(len(members) - 1, self.current_page + 1)
        await self.update_response(interaction)

    @discord.ui.button(label="5 »", style=discord.ButtonStyle.secondary, custom_id="persistent_next_5_button")
    async def next_5(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog, members = await self._get_data()
        if not members:
            await interaction.response.edit_message(content="An error occurred while fetching achievement data.",
                                                    view=None)
            return
        self.current_page = min(len(members) - 1, self.current_page + 5)
        await self.update_response(interaction)

    @discord.ui.button(label="마지막 »", style=discord.ButtonStyle.blurple, custom_id="persistent_last_page_button")
    async def last(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog, members = await self._get_data()
        if not members:
            await interaction.response.edit_message(content="An error occurred while fetching achievement data.",
                                                    view=None)
            return
        self.current_page = len(members) - 1
        await self.update_response(interaction)


class Achievements(commands.Cog):
    GENERAL_ACHIEVEMENTS = {
        "🎯 Achievement Hunter": "10개의 일반 업적을 달성하세요.",
        "🦋 Social Butterfly I": "100개의 메시지를 작성하세요.",
        "🦋 Social Butterfly II": "500개의 메시지를 작성하세요.",
        "🦋 Social Butterfly III": "1000개의 메시지를 작성하세요.",
        "🗺️ Explorer": "10개의 다른 채널에서 메시지를 작성하세요.",
        "😂 Meme Maker": "50개의 첨부 파일 또는 임베드 메시지를 보내세요.",
        "📚 Knowledge Keeper": "20개의 링크를 공유하세요.",
        "🎄 Holiday Greeter": "5개의 다른 공휴일에 메시지를 보내세요.",
        "🦉 Night Owl": "새벽 5시에서 6시 사이에 메시지를 보내세요.",
        "🦅 Early Bird": "오전 9시에서 10시 사이에 메시지를 보내세요.",
        "🗓️ Daily Devotee": "7일 연속으로 메시지를 보내세요.",
        "⚔️ Weekend Warrior": "10번의 주말에 메시지를 보내세요.",
        "🎂 First Anniversary": "봇과 함께한 1주년을 맞이하세요.",
        "🎖️ Veteran": "서버에 가입한 지 365일이 지나고 메시지를 보내세요.",
        "✨ Boost Buddy": "서버를 부스팅하세요.",
        "🎨 The Collector": "10개의 다른 이모티콘으로 반응하세요.",
        "💬 Reaction Responder": "50개의 다른 메시지에 반응하세요.",
        "👣 First Steps": "첫 번째 명령어를 사용하세요.",
        "🤖 Bot Buddy": "100번 봇과 상호작용하세요.",
        "🗣️ Voice Veteran": "음성 채널에 10시간 동안 접속하세요.",
        "🎧 Loyal Listener": "음성 채널에 50시간 동안 접속하세요."
    }

    HIDDEN_ACHIEVEMENTS = {
        "🤫 The Echo": "봇에게 특별한 인사를 건네보세요.",
        "🕛 Midnight Mystery": "시간의 경계에서 메시지를 남겨보세요.",
        "🪐 Zero Gravity": "혼자만의 공간에서 메시지를 보내보세요.",
        "🔄 Palindrome Pro": "앞으로 읽어도 뒤로 읽어도 같은 메시지를 보내보세요.",
        "🤐 The Unmentionable": "모든 사람의 주의를 끌어보세요.",
        "🙉 I'm Not Listening": "음성 채널에서 소리를 완전히 차단해보세요.",
        "❄️ Code Breaker": "디스코드의 숨겨진 ID를 메시지에 포함해보세요.",
        "👻 Ghost Hunter": "존재하지 않는 유령을 찾아 멘션해보세요.",
        "✒️ Invisible Ink": "모든 내용을 숨긴 메시지를 보내보세요.",
        "📢 Echo Chamber": "다른 사람들과 함께 메아리를 만들어보세요.",
        "🚶 Shadow Lurker": "긴 침묵 후에 다시 나타나보세요.",
        "✏️ Phantom Poster": "흔적을 남기지 않고 사라져보세요.",
        "❤️ Secret Admirer": "오래된 메시지에 첫 번째 반응을 남겨보세요.",
        "📍 Error 404": "존재하지 않는 명령어를 찾아보세요.",
        "📟 Ping Master": "누군가의 부름에 빠르게 응답해보세요."
    }

    ACHIEVEMENT_EMOJI_MAP = {
        "Achievement Hunter": "🎯",
        "Social Butterfly I": "🦋",
        "Social Butterfly II": "🦋",
        "Social Butterfly III": "🦋",
        "Explorer": "🗺️",
        "Meme Maker": "😂",
        "Knowledge Keeper": "📚",
        "Holiday Greeter": "🎄",
        "Night Owl": "🦉",
        "Early Bird": "🦅",
        "Daily Devotee": "🗓️",
        "Weekend Warrior": "⚔️",
        "First Anniversary": "🎂",
        "Veteran": "🎖️",
        "Boost Buddy": "✨",
        "The Collector": "🎨",
        "Reaction Responder": "💬",
        "First Steps": "👣",
        "Bot Buddy": "🤖",
        "Voice Veteran": "🗣️",
        "Loyal Listener": "🎧",
        "The Echo": "🤫",
        "Midnight Mystery": "🕛",
        "Zero Gravity": "🪐",
        "Palindrome Pro": "🔄",
        "The Unmentionable": "🤐",
        "I'm Not Listening": "🙉",
        "Code Breaker": "❄️",
        "Ghost Hunter": "👻",
        "Invisible Ink": "✒️",
        "Echo Chamber": "📢",
        "Shadow Lurker": "🚶",
        "Phantom Poster": "✏️",
        "Secret Admirer": "❤️",
        "Error 404": "📍",
        "Ping Master": "📟"
    }

    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("업적 시스템")
        self.logger.info("업적 시스템이 초기화되었습니다.")

        # Per-guild data structure - user_id: {guild_id: data}
        self.data = defaultdict(lambda: defaultdict(lambda: {
            "general_unlocked": [],
            "hidden_unlocked": [],
            "message_count": 0,
            "reaction_count": 0,
            "different_reactions": set(),
            "last_message_date": None,
            "daily_streak": 0,
            "weekend_count": 0,
            "weekends_participated": set(),
            "command_count": 0,
            "voice_time": 0.0,
            "first_command_used": False,
            "last_message_text": None,
            "edited_messages_count": 0,
            "join_date": None,
            "last_dm_text": None,
            "channels_visited": set(),
            "message_ids_reacted_to": set(),
            "reaction_responder_count": 0,
            "last_edit_time": None,
            "bot_interactions": 0,
            "helper_hero_count": 0,
            "link_count": 0,
            "consecutive_messages": 0,
            "last_lurker_message": None,
            "meme_count": 0,
            "edit_timestamps": [],
            "holidays_sent": set(),
            "has_boosted": False,
            "bot_pinged": False,
            "voice_join_time": None,
            "last_activity": None,
            "echo_chamber_participants": set(),
            "last_echo_message": None,
            "message_delete_times": [],
        }))
        self.load_data()
        self.voice_update_task.start()
        self.daily_achievements_update.start()

    def load_data(self):
        if os.path.exists(ACHIEVEMENT_DATA_PATH):
            try:
                with open(ACHIEVEMENT_DATA_PATH, 'r') as f:
                    data = json.load(f)

                    # Handle both old format and new format
                    for user_id, user_data in data.items():
                        user_id = int(user_id)

                        if "general_unlocked" in user_data:
                            # Old format - migrate to new format
                            self.logger.info(f"Migrating old format data for user {user_id}")

                            # Convert sets from lists
                            user_data["different_reactions"] = set(user_data.get("different_reactions", []))
                            user_data["channels_visited"] = set(user_data.get("channels_visited", []))
                            user_data["message_ids_reacted_to"] = set(user_data.get("message_ids_reacted_to", []))
                            user_data["holidays_sent"] = set(user_data.get("holidays_sent", []))
                            user_data["weekends_participated"] = set(user_data.get("weekends_participated", []))
                            user_data["echo_chamber_participants"] = set(user_data.get("echo_chamber_participants", []))

                            # Convert datetime strings
                            for dt_field in ["last_message_date", "last_edit_time", "last_lurker_message",
                                             "voice_join_time", "last_activity", "last_echo_message"]:
                                if user_data.get(dt_field):
                                    user_data[dt_field] = datetime.datetime.fromisoformat(user_data[dt_field])

                            user_data["edit_timestamps"] = [
                                datetime.datetime.fromisoformat(ts)
                                for ts in user_data.get("edit_timestamps", [])
                            ]

                            user_data["message_delete_times"] = [
                                datetime.datetime.fromisoformat(ts)
                                for ts in user_data.get("message_delete_times", [])
                            ]

                            self.data[user_id]["migrated"] = user_data

                        else:
                            # New format - per-guild data
                            for guild_id_str, guild_data in user_data.items():
                                guild_id = int(guild_id_str)

                                # Convert sets from lists
                                guild_data["different_reactions"] = set(guild_data.get("different_reactions", []))
                                guild_data["channels_visited"] = set(guild_data.get("channels_visited", []))
                                guild_data["message_ids_reacted_to"] = set(guild_data.get("message_ids_reacted_to", []))
                                guild_data["holidays_sent"] = set(guild_data.get("holidays_sent", []))
                                guild_data["weekends_participated"] = set(guild_data.get("weekends_participated", []))
                                guild_data["echo_chamber_participants"] = set(
                                    guild_data.get("echo_chamber_participants", []))

                                # Convert datetime strings
                                for dt_field in ["last_message_date", "last_edit_time", "last_lurker_message",
                                                 "voice_join_time", "last_activity", "last_echo_message"]:
                                    if guild_data.get(dt_field):
                                        guild_data[dt_field] = datetime.datetime.fromisoformat(guild_data[dt_field])

                                guild_data["edit_timestamps"] = [
                                    datetime.datetime.fromisoformat(ts)
                                    for ts in guild_data.get("edit_timestamps", [])
                                ]

                                guild_data["message_delete_times"] = [
                                    datetime.datetime.fromisoformat(ts)
                                    for ts in guild_data.get("message_delete_times", [])
                                ]

                                self.data[user_id][guild_id] = guild_data

                self.logger.info(f"업적 데이터 로드 완료: {len(self.data)}명의 사용자 데이터")
            except Exception as e:
                self.logger.error("업적 데이터 로드 실패", exc_info=True)
        else:
            if not os.path.exists('data'):
                os.makedirs('data')
            self.save_data()
            self.logger.info("업적 데이터 파일이 없어서 새로 생성했습니다.")

    def save_data(self):
        try:
            with open(ACHIEVEMENT_DATA_PATH, 'w') as f:
                serializable_data = {}
                for user_id, guild_data_dict in self.data.items():
                    serializable_data[user_id] = {}

                    for guild_id, guild_data in guild_data_dict.items():
                        if guild_id == "migrated":
                            continue

                        serializable_data[user_id][guild_id] = {
                            **guild_data,
                            "different_reactions": list(guild_data.get("different_reactions", set())),
                            "channels_visited": list(guild_data.get("channels_visited", set())),
                            "message_ids_reacted_to": list(guild_data.get("message_ids_reacted_to", set())),
                            "holidays_sent": list(guild_data.get("holidays_sent", set())),
                            "weekends_participated": list(guild_data.get("weekends_participated", set())),
                            "echo_chamber_participants": list(guild_data.get("echo_chamber_participants", set())),
                        }

                        # Convert datetime objects to strings
                        for dt_field in ["last_message_date", "last_edit_time", "last_lurker_message",
                                         "voice_join_time", "last_activity", "last_echo_message"]:
                            if guild_data.get(dt_field):
                                serializable_data[user_id][guild_id][dt_field] = guild_data[dt_field].isoformat()

                        serializable_data[user_id][guild_id]["edit_timestamps"] = [
                            ts.isoformat() for ts in guild_data.get("edit_timestamps", [])
                        ]

                        serializable_data[user_id][guild_id]["message_delete_times"] = [
                            ts.isoformat() for ts in guild_data.get("message_delete_times", [])
                        ]

                json.dump(serializable_data, f, indent=4)
                self.logger.debug("업적 데이터 저장 완료")
        except Exception as e:
            self.logger.error("업적 데이터 저장 실패", exc_info=True)

    def get_user_data(self, user_id: int, guild_id: int):
        """Get user data for specific guild"""
        return self.data[user_id][guild_id]

    def cog_unload(self):
        self.voice_update_task.cancel()
        self.daily_achievements_update.cancel()
        self.logger.info("업적 시스템 Cog 언로드됨")

    async def _send_achievement_notification(self, member, achievement_name, is_hidden):
        if not is_feature_enabled(member.guild.id, 'achievements'):
            return

        try:
            achievement_alert_channel_id = get_channel_id(member.guild.id, 'achievement_alert_channel')
            if not achievement_alert_channel_id:
                self.logger.warning("No achievement alert channel configured.", extra={'guild_id': member.guild.id})
                return

            channel = self.bot.get_channel(achievement_alert_channel_id)
            if not channel:
                self.logger.error(f"Achievement alert channel {achievement_alert_channel_id} not found.",
                                  extra={'guild_id': member.guild.id})
                return

            emoji = self.ACHIEVEMENT_EMOJI_MAP.get(achievement_name, '🏆' if not is_hidden else '🤫')
            title = f"{emoji} 새로운 업적 달성! {emoji}"
            description = (
                f"{member.mention} 님이 **{achievement_name}** 업적을 달성했습니다!\n"
                f"🎉 축하합니다!"
            )

            embed = discord.Embed(
                title=title,
                description=description,
                color=discord.Color.gold(),
                timestamp=datetime.datetime.now(datetime.timezone.utc)
            )

            if member.avatar:
                embed.set_thumbnail(url=member.avatar.url)

            await channel.send(embed=embed)
            self.logger.info(f"업적 알림 전송 완료: {member.name} ({achievement_name})", extra={'guild_id': member.guild.id})

        except Exception as e:
            self.logger.error(f"업적 알림 전송 실패 - 사용자: {member.id}, 업적: {achievement_name}", exc_info=True,
                              extra={'guild_id': member.guild.id})

    def unlock_achievement(self, user, achievement_name, is_hidden=False, guild_id=None):
        """Properly handle guild-specific achievements"""
        if guild_id is None:
            if hasattr(user, 'guild') and user.guild:
                guild_id = user.guild.id
            else:
                self.logger.warning(
                    f"Cannot determine guild for achievement unlock: {achievement_name} for user {user.id}")
                return False

        if not is_feature_enabled(guild_id, 'achievements'):
            return False

        user_id = user.id
        user_data = self.get_user_data(user_id, guild_id)
        unlocked_list = user_data["hidden_unlocked"] if is_hidden else user_data["general_unlocked"]

        if achievement_name not in unlocked_list:
            unlocked_list.append(achievement_name)
            self.save_data()
            achievement_type = "히든" if is_hidden else "일반"
            self.logger.info(f"업적 달성: {user.name} (ID: {user_id}) - {achievement_name} ({achievement_type})",
                             extra={'guild_id': guild_id})

            if hasattr(user, 'guild') and user.guild:
                self.bot.loop.create_task(self._send_achievement_notification(user, achievement_name, is_hidden))
                self.bot.loop.create_task(self.post_achievements_display(guild_id))

            # Achievement Hunter check
            if not is_hidden and len(user_data["general_unlocked"]) >= 10:
                self.unlock_achievement(user, "Achievement Hunter", guild_id=guild_id)
            return True
        return False

    # Helper functions for new achievements
    def is_discord_snowflake(self, text):
        """Check if text contains a valid Discord snowflake ID"""
        snowflake_pattern = r'\b\d{17,19}\b'
        return bool(re.search(snowflake_pattern, text))

    def is_palindrome(self, text):
        """Check if text is a palindrome (case-insensitive, ignoring spaces and punctuation)"""
        clean_text = re.sub(r'[^a-zA-Z0-9가-힣]', '', text.lower())
        return len(clean_text) > 3 and clean_text == clean_text[::-1]

    def is_spoiler_only(self, text):
        """Check if entire message is formatted as spoilers"""
        if not text.strip():
            return False
        # Remove spoiler tags and check if anything remains
        no_spoilers = re.sub(r'\|\|.*?\|\|', '', text)
        return not no_spoilers.strip() and '||' in text

    async def count_non_bot_members_online(self, guild):
        """Count non-bot members who are online"""
        online_count = 0
        for member in guild.members:
            if not member.bot and member.status != discord.Status.offline:
                online_count += 1
        return online_count

    async def _get_sorted_members(self, guild_id):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            self.logger.error(f"길드 ID {guild_id}를 찾을 수 없습니다.", extra={'guild_id': guild_id})
            return []

        if not guild.chunked:
            self.logger.info("길드가 완전히 청크되지 않음. 청크 요청 중...", extra={'guild_id': guild_id})
            await guild.chunk()

        total_members = len([m for m in guild.members if not m.bot])
        self.logger.info(f"청크 완료 후 총 비봇 멤버 수: {total_members}", extra={'guild_id': guild_id})

        member_achievements = []
        for member in guild.members:
            if not member.bot:
                user_data = self.data.get(member.id, {}).get(guild_id, {"general_unlocked": [], "hidden_unlocked": []})
                unlocked_count = len(user_data.get("general_unlocked", [])) + len(user_data.get("hidden_unlocked", []))
                member_achievements.append({'member': member, 'count': unlocked_count})

        sorted_members = sorted(member_achievements, key=lambda x: x['count'], reverse=True)
        return [item['member'] for item in sorted_members]

    async def post_achievements_display(self, guild_id):
        if not is_feature_enabled(guild_id, 'achievements'):
            return

        achievement_channel_id = get_channel_id(guild_id, 'achievement_channel')
        if not achievement_channel_id:
            self.logger.warning("No achievement channel configured.", extra={'guild_id': guild_id})
            return

        channel = self.bot.get_channel(achievement_channel_id)
        if not channel:
            self.logger.error(f"Achievement channel {achievement_channel_id} not found.", extra={'guild_id': guild_id})
            return

        try:
            # Delete previous messages
            deleted_count = 0
            async for message in channel.history(limit=50):
                if message.author == self.bot.user and message.embeds and (
                        "업적 현황" in message.embeds[0].title or "업적 목록 및 힌트" in message.embeds[0].title):
                    try:
                        await message.delete()
                        deleted_count += 1
                        self.logger.debug(f"이전 업적 메시지 삭제 (ID: {message.id})", extra={'guild_id': guild_id})
                    except discord.NotFound:
                        pass

            if deleted_count > 0:
                self.logger.info(f"{deleted_count}개의 이전 업적 메시지 삭제 완료", extra={'guild_id': guild_id})

            list_embed = await self._create_achievement_list_embed()
            await channel.send(embed=list_embed)
            self.logger.info("업적 목록 및 힌트 메시지 게시 완료", extra={'guild_id': guild_id})

            sorted_members = await self._get_sorted_members(guild_id)
            if sorted_members:
                view = PersistentAchievementView(self.bot, guild_id, members=sorted_members)
                initial_embed = await view.get_current_embed(self, sorted_members)
                current_message = await channel.send(embed=initial_embed, view=view)
                self.logger.info(f"업적 현황 메시지 게시 완료 (ID: {current_message.id})", extra={'guild_id': guild_id})
            else:
                await channel.send("업적을 달성한 멤버가 없습니다.")
                self.logger.warning("업적을 달성한 멤버가 없습니다", extra={'guild_id': guild_id})

        except Exception as e:
            self.logger.error("업적 현황 메시지 게시 실패", exc_info=True, extra={'guild_id': guild_id})

    async def _create_achievements_embed(self, member: discord.Member, rank: int, total_members: int) -> discord.Embed:
        user_id = member.id
        guild_id = member.guild.id
        user_data = self.data.get(user_id, {}).get(guild_id, {"general_unlocked": [], "hidden_unlocked": []})
        general_unlocked = user_data.get("general_unlocked", [])
        hidden_unlocked = user_data.get("hidden_unlocked", [])

        total_general = len(self.GENERAL_ACHIEVEMENTS)
        total_hidden = len(self.HIDDEN_ACHIEVEMENTS)
        total_achievements = total_general + total_hidden
        unlocked_count = len(general_unlocked) + len(hidden_unlocked)
        progress = f"{unlocked_count}/{total_achievements}"

        embed = discord.Embed(
            title=f"업적 현황 - {member.display_name} (Rank {rank}/{total_members})",
            description=f"업적 달성 현황: {progress}",
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)

        if general_unlocked:
            general_list = ""
            for ach in general_unlocked:
                emoji = self.ACHIEVEMENT_EMOJI_MAP.get(ach, '🏆')
                general_list += f"{emoji} {ach}\n"
            embed.add_field(name=f"🏆 일반 업적 ({len(general_unlocked)}/{total_general})",
                            value=general_list.strip() or "아직 달성한 일반 업적이 없습니다.", inline=False)
        else:
            embed.add_field(name=f"🏆 일반 업적 (0/{total_general})", value="아직 달성한 일반 업적이 없습니다.", inline=False)

        if hidden_unlocked:
            hidden_list = ""
            for ach in hidden_unlocked:
                emoji = self.ACHIEVEMENT_EMOJI_MAP.get(ach, '🤫')
                hidden_list += f"{emoji} {ach}\n"
            embed.add_field(name=f"🤫 히든 업적 ({len(hidden_unlocked)}/{total_hidden})",
                            value=hidden_list.strip() or "아직 달성한 히든 업적이 없습니다.", inline=False)
        else:
            embed.add_field(name=f"🤫 히든 업적 (0/{total_hidden})", value="아직 달성한 히든 업적이 없습니다.", inline=False)

        return embed

    async def _create_achievement_list_embed(self) -> discord.Embed:
        general_list = "\n".join(f"**{name}**: {desc}" for name, desc in self.GENERAL_ACHIEVEMENTS.items())
        hidden_list = "\n".join(f"**{name}**: {desc}" for name, desc in self.HIDDEN_ACHIEVEMENTS.items())

        embed = discord.Embed(
            title="업적 목록 및 힌트",
            description="아래는 봇에서 달성할 수 있는 모든 업적 목록입니다. 히든 업적은 힌트로만 제공됩니다!",
            color=discord.Color.green()
        )
        embed.add_field(name=f"일반 업적 ({len(self.GENERAL_ACHIEVEMENTS)})", value=general_list, inline=False)
        embed.add_field(name=f"히든 업적 힌트 ({len(self.HIDDEN_ACHIEVEMENTS)})", value=hidden_list, inline=False)
        return embed

    @commands.Cog.listener()
    async def on_ready(self):
        self.logger.info("업적 시스템 준비 완료")

        # Handle migration for users in current guilds
        await self._handle_migration()

        # Post achievement displays for all configured servers
        all_configs = get_all_server_configs()
        for guild_id_str, config in all_configs.items():
            if config.get('features', {}).get('achievements', False):
                guild_id = int(guild_id_str)
                guild = self.bot.get_guild(guild_id)
                if guild:
                    self.logger.info("봇 시작 시 길드 청킹 강제 실행 중...", extra={'guild_id': guild_id})
                    await guild.chunk()
                    total_members = len([m for m in guild.members if not m.bot])
                    self.logger.info(f"길드 청킹 완료. 총 비봇 멤버 수: {total_members}", extra={'guild_id': guild_id})

                    await self.post_achievements_display(guild_id)

    async def _handle_migration(self):
        """Handle migration from old format to new guild-specific format"""
        migrated_users = []
        for user_id, guild_data_dict in self.data.items():
            if "migrated" in guild_data_dict:
                migrated_data = guild_data_dict.pop("migrated")
                migrated_users.append(user_id)

                # Copy migrated data to all guilds where this user is a member
                for guild in self.bot.guilds:
                    if is_feature_enabled(guild.id, 'achievements'):
                        member = guild.get_member(user_id)
                        if member and not member.bot:
                            # Copy data to this guild
                            self.data[user_id][guild.id] = migrated_data.copy()
                            self.logger.info(f"Migrated data for user {user_id} to guild {guild.id}")

        if migrated_users:
            self.logger.info(f"Migration completed for {len(migrated_users)} users")
            self.save_data()

    @tasks.loop(time=dt_time(hour=4, minute=0))
    async def daily_achievements_update(self):
        try:
            self.logger.info("일일 업적 업데이트 시작.")

            # Update achievements for all configured servers
            all_configs = get_all_server_configs()
            for guild_id_str, config in all_configs.items():
                if config.get('features', {}).get('achievements', False):
                    guild_id = int(guild_id_str)
                    await self.post_achievements_display(guild_id)

            self.logger.info("일일 업적 업데이트 완료.")
        except Exception as e:
            self.logger.error("일일 업적 업데이트 실패", exc_info=True)

    @daily_achievements_update.before_loop
    async def before_daily_achievements_update(self):
        await self.bot.wait_until_ready()
        self.logger.info("일일 업적 업데이터가 봇이 준비될 때까지 기다리는 중...")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.bot:
            return

        user_data = self.get_user_data(member.id, member.guild.id)
        user_data["join_date"] = member.joined_at.isoformat()
        self.save_data()
        self.logger.info(f"새 멤버 가입 기록: {member.name} (ID: {member.id})", extra={'guild_id': member.guild.id})

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        # Only track if achievements are enabled for this server
        if not is_feature_enabled(after.guild.id, 'achievements'):
            return

        if before.premium_since is None and after.premium_since is not None:
            user_data = self.get_user_data(after.id, after.guild.id)
            if not user_data.get("has_boosted"):
                self.unlock_achievement(after, "Boost Buddy", guild_id=after.guild.id)
                user_data["has_boosted"] = True
                self.save_data()
                self.logger.info(f"서버 부스팅 업적 달성: {after.name} (ID: {after.id})", extra={'guild_id': after.guild.id})

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        # Skip if not in a guild or achievements not enabled
        if not message.guild or not is_feature_enabled(message.guild.id, 'achievements'):
            return

        user_id = message.author.id
        guild_id = message.guild.id
        user_data = self.get_user_data(user_id, guild_id)
        now = datetime.datetime.now(datetime.timezone.utc)

        # Handle DM messages for The Echo achievement
        if isinstance(message.channel, discord.DMChannel):
            if "안녕" in message.content:
                # For DMs, find the first guild where achievements are enabled and the user is a member
                for guild in self.bot.guilds:
                    if is_feature_enabled(guild.id, 'achievements'):
                        member = guild.get_member(user_id)
                        if member:
                            self.unlock_achievement(member, "The Echo", is_hidden=True, guild_id=guild.id)
                            break
            self.save_data()
            return

        # Update user activity timestamp
        user_data["last_activity"] = now

        # Set join date if not already set
        if not user_data.get("join_date") and message.author.joined_at:
            user_data["join_date"] = message.author.joined_at.isoformat()

        # First Anniversary check
        if user_data.get("join_date"):
            join_date = datetime.datetime.fromisoformat(user_data["join_date"])
            if now.month == join_date.month and now.day == join_date.day and (now - join_date).days >= 365:
                self.unlock_achievement(message.author, "First Anniversary", guild_id=guild_id)

        # Veteran achievement
        if user_data.get("join_date"):
            join_date = datetime.datetime.fromisoformat(user_data["join_date"])
            if (now - join_date).days >= 365:
                self.unlock_achievement(message.author, "Veteran", guild_id=guild_id)

        # Message count and related achievements
        user_data["message_count"] += 1
        user_data["channels_visited"].add(message.channel.id)

        if len(user_data["channels_visited"]) >= 10:
            self.unlock_achievement(message.author, "Explorer", guild_id=guild_id)

        if user_data["message_count"] >= 100:
            self.unlock_achievement(message.author, "Social Butterfly I", guild_id=guild_id)
        if user_data["message_count"] >= 500:
            self.unlock_achievement(message.author, "Social Butterfly II", guild_id=guild_id)
        if user_data["message_count"] >= 1000:
            self.unlock_achievement(message.author, "Social Butterfly III", guild_id=guild_id)

        # Meme Maker achievement
        if message.attachments or message.embeds:
            user_data["meme_count"] = user_data.get("meme_count", 0) + 1
            if user_data["meme_count"] >= 50:
                self.unlock_achievement(message.author, "Meme Maker", guild_id=guild_id)

        # Knowledge Keeper (link) achievement
        if any(url in message.content for url in ["http://", "https://"]):
            user_data["link_count"] = user_data.get("link_count", 0) + 1
            if user_data["link_count"] >= 20:
                self.unlock_achievement(message.author, "Knowledge Keeper", guild_id=guild_id)

        # Holiday Greeter achievement
        today_holiday = None
        for holiday_name, holiday_info in HOLIDAYS.items():
            if now.month == holiday_info['month'] and now.day == holiday_info['day']:
                today_holiday = holiday_name
                break
        if today_holiday and today_holiday not in user_data["holidays_sent"]:
            user_data["holidays_sent"].add(today_holiday)
            if len(user_data["holidays_sent"]) >= 5:
                self.unlock_achievement(message.author, "Holiday Greeter", guild_id=guild_id)

        # Midnight Mystery achievement (23:55-00:05)
        hour = now.hour
        minute = now.minute
        if (hour == 23 and minute >= 55) or (hour == 0 and minute <= 5):
            self.unlock_achievement(message.author, "Midnight Mystery", is_hidden=True, guild_id=guild_id)

        # Night Owl achievement (5 AM - 6 AM)
        if 5 <= now.hour < 6:
            self.unlock_achievement(message.author, "Night Owl", guild_id=guild_id)

        # Early Bird achievement (9 AM - 10 AM)
        if 9 <= now.hour < 10:
            self.unlock_achievement(message.author, "Early Bird", guild_id=guild_id)

        # Zero Gravity achievement - only user online
        online_count = await self.count_non_bot_members_online(message.guild)
        if online_count == 1:  # Only this user is online
            self.unlock_achievement(message.author, "Zero Gravity", is_hidden=True, guild_id=guild_id)

        # Palindrome Pro achievement
        if self.is_palindrome(message.content):
            self.unlock_achievement(message.author, "Palindrome Pro", is_hidden=True, guild_id=guild_id)

        # The Unmentionable achievement
        if "@everyone" in message.content or "@here" in message.content:
            self.unlock_achievement(message.author, "The Unmentionable", is_hidden=True, guild_id=guild_id)

        # Code Breaker achievement
        if self.is_discord_snowflake(message.content):
            self.unlock_achievement(message.author, "Code Breaker", is_hidden=True, guild_id=guild_id)

        # Ghost Hunter achievement - mention the specific ghost user ID
        if "1365499246962540606" in message.content and "<@1365499246962540606>" in message.content:
            self.unlock_achievement(message.author, "Ghost Hunter", is_hidden=True, guild_id=guild_id)

        # Invisible Ink achievement
        if self.is_spoiler_only(message.content):
            self.unlock_achievement(message.author, "Invisible Ink", is_hidden=True, guild_id=guild_id)

        # Echo Chamber achievement - 3+ people sending same message
        clean_content = message.content.strip().lower()
        if clean_content and len(clean_content) > 0:
            # Check if this is part of an echo chamber
            recent_messages = []
            async for msg in message.channel.history(limit=10, before=message):
                if msg.content.strip().lower() == clean_content:
                    recent_messages.append(msg)
                else:
                    break

            # If we have 2+ previous identical messages, this creates an echo chamber
            if len(recent_messages) >= 2:
                # Get all unique authors in the chain (including current message author)
                authors = {message.author.id}
                for msg in recent_messages:
                    authors.add(msg.author.id)

                # Award achievement to all participants if we have 3+ unique people
                if len(authors) >= 3:
                    for author_id in authors:
                        member = message.guild.get_member(author_id)
                        if member and not member.bot:
                            self.unlock_achievement(member, "Echo Chamber", is_hidden=True, guild_id=guild_id)

        # Shadow Lurker - message after 7 days of inactivity
        if user_data.get("last_activity"):
            time_diff = (now - user_data["last_activity"]).total_seconds()
            if time_diff >= 604800:  # 7 days in seconds
                self.unlock_achievement(message.author, "Shadow Lurker", is_hidden=True, guild_id=guild_id)

        # Daily Devotee achievement - proper streak calculation
        today = now.date()
        if user_data.get("last_message_date"):
            last_date = user_data["last_message_date"].date()
            days_diff = (today - last_date).days

            if days_diff == 1:
                # Consecutive day
                user_data["daily_streak"] += 1
            elif days_diff == 0:
                # Same day, don't change streak
                pass
            else:
                # Streak broken, start over
                user_data["daily_streak"] = 1
        else:
            # First message ever
            user_data["daily_streak"] = 1

        user_data["last_message_date"] = now

        if user_data["daily_streak"] >= 7:
            self.unlock_achievement(message.author, "Daily Devotee", guild_id=guild_id)

        # Weekend Warrior achievement - count actual weekends
        if now.weekday() >= 5:  # Saturday (5) or Sunday (6)
            year = now.year
            week = now.isocalendar()[1]
            weekend_id = f"{year}-{week}"

            if weekend_id not in user_data["weekends_participated"]:
                user_data["weekends_participated"].add(weekend_id)
                user_data["weekend_count"] = len(user_data["weekends_participated"])

                if user_data["weekend_count"] >= 10:
                    self.unlock_achievement(message.author, "Weekend Warrior", guild_id=guild_id)

        # Error 404 achievement check
        if message.content.startswith('/'):
            try:
                command_name = message.content.split(' ')[0][1:].lower()
                all_slash_commands = [c.name.lower() for c in self.bot.tree.get_commands(guild=message.guild)]
                if command_name not in all_slash_commands:
                    self.unlock_achievement(message.author, "Error 404", is_hidden=True, guild_id=guild_id)
            except IndexError:
                pass

        self.save_data()

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.author.bot:
            return
        if not message.guild or not is_feature_enabled(message.guild.id, 'achievements'):
            return

        user_id = message.author.id
        guild_id = message.guild.id
        user_data = self.get_user_data(user_id, guild_id)
        now = datetime.datetime.now(datetime.timezone.utc)

        # Phantom Poster - message deleted within 5 seconds
        message_age = (now - message.created_at.replace(tzinfo=datetime.timezone.utc)).total_seconds()
        if message_age <= 5:
            self.unlock_achievement(message.author, "Phantom Poster", is_hidden=True, guild_id=guild_id)

        self.save_data()

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if after.author.bot:
            return
        if not after.guild or not is_feature_enabled(after.guild.id, 'achievements'):
            return

        user_id = after.author.id
        guild_id = after.guild.id
        user_data = self.get_user_data(user_id, guild_id)
        now = datetime.datetime.now(datetime.timezone.utc)
        user_data["last_edit_time"] = now
        self.save_data()

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.bot or not reaction.message.guild or not is_feature_enabled(reaction.message.guild.id, 'achievements'):
            return

        user_id = user.id
        guild_id = reaction.message.guild.id
        message_id = reaction.message.id
        user_data = self.get_user_data(user_id, guild_id)
        now = datetime.datetime.now(datetime.timezone.utc)

        # Secret Admirer achievement - first reaction to message over 24 hours old
        message_age = (now - reaction.message.created_at.replace(tzinfo=datetime.timezone.utc)).total_seconds()
        if message_age >= 86400 and len(reaction.message.reactions) == 1:  # 24 hours, first reaction
            # Check if this is actually the first reaction
            total_reactions = sum(r.count for r in reaction.message.reactions)
            if total_reactions == 1:
                self.unlock_achievement(user, "Secret Admirer", is_hidden=True, guild_id=guild_id)

        # The Collector achievement
        emoji_str = str(reaction.emoji)
        if emoji_str not in user_data["different_reactions"]:
            user_data["different_reactions"].add(emoji_str)
            if len(user_data["different_reactions"]) >= 10:
                self.unlock_achievement(user, "The Collector", guild_id=guild_id)

        # Reaction Responder achievement
        if message_id not in user_data["message_ids_reacted_to"]:
            user_data["reaction_responder_count"] = user_data.get("reaction_responder_count", 0) + 1
            user_data["message_ids_reacted_to"].add(message_id)
            if user_data["reaction_responder_count"] >= 50:
                self.unlock_achievement(user, "Reaction Responder", guild_id=guild_id)

        self.save_data()

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.user.bot:
            return
        if not interaction.guild or not is_feature_enabled(interaction.guild.id, 'achievements'):
            return

        user_id = interaction.user.id
        guild_id = interaction.guild.id
        user_data = self.get_user_data(user_id, guild_id)

        if interaction.type == discord.InteractionType.application_command:
            # First Steps achievement
            if not user_data.get("first_command_used", False):
                self.unlock_achievement(interaction.user, "First Steps", guild_id=guild_id)
                user_data["first_command_used"] = True

            # Bot Buddy achievement
            user_data["bot_interactions"] = user_data.get("bot_interactions", 0) + 1
            if user_data["bot_interactions"] >= 100:
                self.unlock_achievement(interaction.user, "Bot Buddy", guild_id=guild_id)

            # Ping Master achievement (for ping-related commands)
            if interaction.command and "ping" in interaction.command.name.lower():
                self.unlock_achievement(interaction.user, "Ping Master", is_hidden=True, guild_id=guild_id)

        self.save_data()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot or not member.guild or not is_feature_enabled(member.guild.id, 'achievements'):
            return

        user_id = member.id
        guild_id = member.guild.id
        user_data = self.get_user_data(user_id, guild_id)
        now = datetime.datetime.now(datetime.timezone.utc)

        # I'm Not Listening achievement - user deafened themselves
        if (before.self_deaf != after.self_deaf and after.self_deaf and
                after.channel is not None):
            self.unlock_achievement(member, "I'm Not Listening", is_hidden=True, guild_id=guild_id)

        # Joined a voice channel
        if before.channel is None and after.channel is not None:
            user_data["voice_join_time"] = now
            self.logger.debug(f"사용자 {member.name}가 음성 채널에 접속함.", extra={'guild_id': guild_id})

        # Left a voice channel
        elif before.channel is not None and after.channel is None:
            if user_data.get("voice_join_time"):
                join_time = user_data["voice_join_time"]
                if join_time.tzinfo is None:
                    join_time = join_time.replace(tzinfo=datetime.timezone.utc)

                duration = (now - join_time).total_seconds()
                user_data["voice_time"] = user_data.get("voice_time", 0) + duration
                user_data["voice_join_time"] = None
                self.save_data()
                self.logger.debug(f"사용자 {member.name}가 음성 채널을 떠남. 접속 시간: {duration:.2f}초",
                                  extra={'guild_id': guild_id})

    @tasks.loop(minutes=5)
    async def voice_update_task(self):
        try:
            now = datetime.datetime.now(datetime.timezone.utc)
            self.logger.debug("음성 시간 업데이트 작업 실행 중.")

            for guild in self.bot.guilds:
                if not is_feature_enabled(guild.id, 'achievements'):
                    continue

                for member in guild.members:
                    if member.bot or not member.voice or not member.voice.channel:
                        continue

                    user_data = self.get_user_data(member.id, guild.id)

                    if not user_data.get("voice_join_time"):
                        user_data["voice_join_time"] = now
                        continue

                    voice_join_time = user_data["voice_join_time"]
                    if voice_join_time.tzinfo is None:
                        voice_join_time = voice_join_time.replace(tzinfo=datetime.timezone.utc)

                    # Calculate time since last update (5 minutes max)
                    duration = min((now - voice_join_time).total_seconds(), 300)
                    user_data["voice_time"] = user_data.get("voice_time", 0) + duration
                    user_data["voice_join_time"] = now

                    # Voice Veteran (10 hours = 36000 seconds)
                    if (user_data["voice_time"] >= 36000 and
                            "Voice Veteran" not in user_data.get("general_unlocked", [])):
                        self.unlock_achievement(member, "Voice Veteran", guild_id=guild.id)

                    # Loyal Listener (50 hours = 180000 seconds)
                    if (user_data["voice_time"] >= 180000 and
                            "Loyal Listener" not in user_data.get("general_unlocked", [])):
                        self.unlock_achievement(member, "Loyal Listener", guild_id=guild.id)

            self.save_data()
        except Exception as e:
            self.logger.error("음성 시간 업데이트 실패", exc_info=True)

    @voice_update_task.before_loop
    async def before_voice_update_task(self):
        await self.bot.wait_until_ready()
        self.logger.info("음성 시간 업데이트 태스크가 봇이 준비될 때까지 기다리는 중...")


async def setup(bot):
    await bot.add_cog(Achievements(bot))