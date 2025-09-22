# cogs/scrim.py
from typing import Optional, Dict, List
import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
from datetime import datetime, timezone, timedelta
import pytz
import random
import asyncio
import traceback

from utils.logger import get_logger
from utils import config


class GameSelectView(discord.ui.View):
    """게임 선택 뷰 (역할 태그 지원)"""

    def __init__(self, bot, guild_id: int):
        super().__init__(timeout=900)
        self.bot = bot
        self.guild_id = guild_id
        self.selected_game = None
        self.selected_role_id = None
        self.logger = get_logger("내부 매치")
        self.message = None  # To store the message this view is attached to

        # 게임 옵션과 역할 ID
        self.game_options = [
            discord.SelectOption(
                label="발로란트",
                value="VAL:1209013681753563156",
                description="라이엇 게임즈의 전술 FPS",
                emoji="🎯"
            ),
            discord.SelectOption(
                label="팀파이트 택틱스",
                value="TFT:1333664246608957461",
                description="오토 배틀러 전략 게임",
                emoji="♟️"
            ),
            discord.SelectOption(
                label="리그 오브 레전드",
                value="LOL:1209014051317743626",
                description="라이엇 게임즈의 MOBA",
                emoji="⚔️"
            ),
            discord.SelectOption(
                label="배틀그라운드",
                value="PUBG:1417766140121186359",
                description="배틀 로얄 슈팅 게임",
                emoji="🔫"
            ),
            discord.SelectOption(
                label="기타 게임",
                value="OG:1417766914003959878",
                description="다른 모든 게임",
                emoji="🎮"
            )
        ]

        self.game_select = discord.ui.Select(
            placeholder="게임 선택...",
            options=self.game_options,
            custom_id="game_select"
        )
        self.game_select.callback = self.game_selected
        self.add_item(self.game_select)

    async def on_timeout(self):
        """Handle view timeout"""
        try:
            for item in self.children:
                item.disabled = True

            if self.message:
                embed = discord.Embed(
                    title="⏱️ 시간 초과",
                    description="이 메뉴가 만료되었습니다. 새로운 내전 생성을 시작해주세요.",
                    color=discord.Color.red()
                )
                await self.message.edit(embed=embed, view=self)
        except Exception as e:
            self.logger.error(f"Timeout error in GameSelectView: {traceback.format_exc()}")

    async def game_selected(self, interaction: discord.Interaction):
        """게임 선택 처리"""
        try:
            await interaction.response.defer()

            selection = self.game_select.values[0]
            game_name, role_id = selection.split(":")

            game_names = {
                "VAL": "발로란트",
                "TFT": "팀파이트 택틱스",
                "LOL": "리그 오브 레전드",
                "PUBG": "배틀그라운드",
                "OG": "기타 게임"
            }

            self.selected_game = game_names.get(game_name, game_name)
            self.selected_role_id = int(role_id)

            gamemode_view = GameModeSelectView(
                self.bot, self.guild_id, self.selected_game, self.selected_role_id
            )

            embed = discord.Embed(
                title="🎮 게임 모드 선택",
                description=f"**선택된 게임:** {self.selected_game}\n\n이제 게임 모드를 선택하세요:",
                color=discord.Color.blue()
            )

            await interaction.edit_original_response(embed=embed, view=gamemode_view)
            gamemode_view.message = await interaction.original_response()

        except Exception as e:
            self.logger.error(f"Game selection error: {traceback.format_exc()}")
            try:
                await interaction.followup.send(f"⚠ 오류가 발생했습니다: {str(e)}", ephemeral=True)
            except:
                pass


class GameModeSelectView(discord.ui.View):
    """게임 모드 선택 뷰"""

    def __init__(self, bot, guild_id: int, game: str, role_id: int):
        super().__init__(timeout=900)
        self.bot = bot
        self.guild_id = guild_id
        self.game = game
        self.role_id = role_id
        self.selected_gamemode = None
        self.logger = get_logger("내부 매치")
        self.message = None

        # 선택된 게임에 따라 게임 모드 옵션 설정
        gamemode_options = self.get_gamemode_options(game)

        self.gamemode_select = discord.ui.Select(
            placeholder="게임 모드 선택...",
            options=gamemode_options,
            custom_id="gamemode_select"
        )
        self.gamemode_select.callback = self.gamemode_selected
        self.add_item(self.gamemode_select)

        # 뒤로 가기 버튼
        back_button = discord.ui.Button(
            label="뒤로",
            style=discord.ButtonStyle.secondary,
            emoji="⬅️"
        )
        back_button.callback = self.back_to_game_selection
        self.add_item(back_button)

    async def on_timeout(self):
        """Handle view timeout"""
        try:
            for item in self.children:
                item.disabled = True

            if self.message:
                embed = discord.Embed(
                    title="⏱️ 시간 초과",
                    description="이 메뉴가 만료되었습니다. 새로운 내전 생성을 시작해주세요.",
                    color=discord.Color.red()
                )
                await self.message.edit(embed=embed, view=self)
        except Exception as e:
            self.logger.error(f"Timeout error in GameModeSelectView: {traceback.format_exc()}")

    def get_gamemode_options(self, game: str) -> List[discord.SelectOption]:
        """선택된 게임에 따라 게임 모드 옵션 가져오기"""
        gamemode_map = {
            "발로란트": [
                discord.SelectOption(label="5v5 경쟁전", value="5v5", emoji="🏆"),
                discord.SelectOption(label="5v5 비경쟁전", value="5v5 Unrated", emoji="🎯"),
                discord.SelectOption(label="사용자 지정 게임", value="Custom", emoji="⚙️")
            ],
            "리그 오브 레전드": [
                discord.SelectOption(label="5v5 소환사의 협곡", value="5v5 SR", emoji="🏰"),
                discord.SelectOption(label="5v5 ARAM", value="5v5 ARAM", emoji="❄️"),
                discord.SelectOption(label="사용자 지정 게임", value="Custom", emoji="⚙️")
            ],
            "팀파이트 택틱스": [
                discord.SelectOption(label="8인 로비", value="8P Lobby", emoji="♟️"),
                discord.SelectOption(label="토너먼트", value="Tournament", emoji="🏆")
            ],
            "배틀그라운드": [
                discord.SelectOption(label="스쿼드 (4v4v...)", value="Squad", emoji="👥"),
                discord.SelectOption(label="듀오 (2v2v...)", value="Duo", emoji="👫"),
                discord.SelectOption(label="솔로", value="Solo", emoji="🕴️"),
                discord.SelectOption(label="사용자 지정 룸", value="Custom", emoji="⚙️")
            ]
        }

        return gamemode_map.get(game, [
            discord.SelectOption(label="표준", value="Standard", emoji="🎮"),
            discord.SelectOption(label="사용자 지정", value="Custom", emoji="⚙️")
        ])

    async def gamemode_selected(self, interaction: discord.Interaction):
        """게임 모드 선택 처리"""
        try:
            await interaction.response.defer()
            self.selected_gamemode = self.gamemode_select.values[0]

            tier_view = TierSelectView(
                self.bot, self.guild_id, self.game, self.selected_gamemode, self.role_id
            )

            embed = discord.Embed(
                title="🏆 티어 범위 선택",
                description=f"**게임:** {self.game}\n**모드:** {self.selected_gamemode}\n\n티어 범위를 선택하세요:",
                color=discord.Color.gold()
            )

            await interaction.edit_original_response(embed=embed, view=tier_view)
            tier_view.message = await interaction.original_response()

        except Exception as e:
            self.logger.error(f"Gamemode selection error: {traceback.format_exc()}")
            try:
                await interaction.followup.send(f"⚠ 오류가 발생했습니다: {str(e)}", ephemeral=True)
            except:
                pass

    async def back_to_game_selection(self, interaction: discord.Interaction):
        """게임 선택으로 돌아가기"""
        try:
            await interaction.response.defer()
            game_view = GameSelectView(self.bot, self.guild_id)

            embed = discord.Embed(
                title="🎮 게임 선택",
                description="내전을 위한 게임을 선택하세요:",
                color=discord.Color.green()
            )

            await interaction.edit_original_response(embed=embed, view=game_view)
            game_view.message = await interaction.original_response()
        except Exception as e:
            self.logger.error(f"Back to game selection error: {traceback.format_exc()}")
            try:
                await interaction.followup.send(f"⚠ 오류가 발생했습니다: {str(e)}", ephemeral=True)
            except:
                pass


class TierSelectView(discord.ui.View):
    """티어 범위 선택 뷰"""

    def __init__(self, bot, guild_id: int, game: str, gamemode: str, role_id: int):
        super().__init__(timeout=900)
        self.bot = bot
        self.guild_id = guild_id
        self.game = game
        self.gamemode = gamemode
        self.role_id = role_id
        self.selected_tier = None
        self.logger = get_logger("내부 매치")
        self.message = None

        tier_options = [
            discord.SelectOption(label="모든 티어", value="All tiers", emoji="🌐"),
            discord.SelectOption(label="아이언 - 브론즈", value="Iron-Bronze",
                                 emoji="<:valorantbronze:1367050339987095563>"),
            discord.SelectOption(label="실버 - 골드", value="Silver-Gold", emoji="<:valorantgold:1367050331242106951>"),
            discord.SelectOption(label="골드 - 플래티넘", value="Gold-Platinum",
                                 emoji="<:valorantplatinum:1367055859435175986>"),
            discord.SelectOption(label="플래티넘 - 다이아몬드", value="Plat-Diamond",
                                 emoji="<:valorantdiamond:1367055861351972905>"),
            discord.SelectOption(label="초월자", value="Ascendant", emoji="<:valorantascendant:1367050328976920606>"),
            discord.SelectOption(label="불멸+", value="Immortal+", emoji="<:valorantimmortal:1367050346874011668>"),
            discord.SelectOption(label="초보자 친화", value="Beginner", emoji="🌱"),
            discord.SelectOption(label="경쟁전", value="Competitive", emoji="🏆")
        ]

        self.tier_select = discord.ui.Select(
            placeholder="티어 범위 선택...",
            options=tier_options,
            custom_id="tier_select"
        )
        self.tier_select.callback = self.tier_selected
        self.add_item(self.tier_select)

        back_button = discord.ui.Button(label="뒤로", style=discord.ButtonStyle.secondary, emoji="⬅️")
        back_button.callback = self.back_to_gamemode_selection
        self.add_item(back_button)

    async def on_timeout(self):
        """Handle view timeout"""
        try:
            for item in self.children:
                item.disabled = True

            if self.message:
                embed = discord.Embed(
                    title="⏱️ 시간 초과",
                    description="이 메뉴가 만료되었습니다. 새로운 내전 생성을 시작해주세요.",
                    color=discord.Color.red()
                )
                await self.message.edit(embed=embed, view=self)
        except Exception as e:
            self.logger.error(f"Timeout error in TierSelectView: {traceback.format_exc()}")

    async def tier_selected(self, interaction: discord.Interaction):
        """티어 선택 처리"""
        try:
            await interaction.response.defer()
            self.selected_tier = self.tier_select.values[0]

            time_view = TimeSelectView(
                self.bot, self.guild_id, self.game, self.gamemode,
                self.selected_tier, self.role_id
            )

            embed = discord.Embed(
                title="⏰ 시작 시간 선택",
                description=f"**게임:** {self.game}\n**모드:** {self.gamemode}\n**티어:** {self.selected_tier}\n\n내전은 언제 시작해야 하나요?",
                color=discord.Color.orange()
            )

            await interaction.edit_original_response(embed=embed, view=time_view)
            time_view.message = await interaction.original_response()

        except Exception as e:
            self.logger.error(f"Tier selection error: {traceback.format_exc()}")
            try:
                await interaction.followup.send(f"⚠ 오류가 발생했습니다: {str(e)}", ephemeral=True)
            except:
                pass

    async def back_to_gamemode_selection(self, interaction: discord.Interaction):
        """게임 모드 선택으로 돌아가기"""
        try:
            await interaction.response.defer()
            gamemode_view = GameModeSelectView(self.bot, self.guild_id, self.game, self.role_id)
            embed = discord.Embed(
                title="🎮 게임 모드 선택",
                description=f"**선택된 게임:** {self.game}\n\n이제 게임 모드를 선택하세요:",
                color=discord.Color.blue()
            )
            await interaction.edit_original_response(embed=embed, view=gamemode_view)
            gamemode_view.message = await interaction.original_response()
        except Exception as e:
            self.logger.error(f"Back to gamemode selection error: {traceback.format_exc()}")
            try:
                await interaction.followup.send(f"⚠ 오류가 발생했습니다: {str(e)}", ephemeral=True)
            except:
                pass


class TimeSelectView(discord.ui.View):
    """시작 시간 선택 뷰"""

    def __init__(self, bot, guild_id: int, game: str, gamemode: str, tier: str, role_id: int):
        super().__init__(timeout=900)
        self.bot = bot
        self.guild_id = guild_id
        self.game = game
        self.gamemode = gamemode
        self.tier = tier
        self.role_id = role_id
        self.selected_time = None
        self.logger = get_logger("내부 매치")
        self.message = None

        time_options = [
            discord.SelectOption(label="30분 후", value="30min", emoji="⏱️"),
            discord.SelectOption(label="1시간 후", value="1hour", emoji="🕐"),
            discord.SelectOption(label="2시간 후", value="2hour", emoji="🕑"),
            discord.SelectOption(label="오늘 저녁 8시", value="tonight", emoji="🌙"),
            discord.SelectOption(label="사용자 지정", value="custom", emoji="⚙️")
        ]

        self.time_select = discord.ui.Select(placeholder="시작 시간 선택...", options=time_options, custom_id="time_select")
        self.time_select.callback = self.time_selected
        self.add_item(self.time_select)

        back_button = discord.ui.Button(label="뒤로", style=discord.ButtonStyle.secondary, emoji="⬅️")
        back_button.callback = self.back_to_tier_selection
        self.add_item(back_button)

    async def on_timeout(self):
        """Handle view timeout"""
        try:
            for item in self.children:
                item.disabled = True
            if self.message:
                embed = discord.Embed(
                    title="⏱️ 시간 초과",
                    description="이 메뉴가 만료되었습니다. 새로운 내전 생성을 시작해주세요.",
                    color=discord.Color.red()
                )
                await self.message.edit(embed=embed, view=self)
        except Exception as e:
            self.logger.error(f"Timeout error in TimeSelectView: {traceback.format_exc()}")

    async def time_selected(self, interaction: discord.Interaction):
        """시간 선택 처리"""
        try:
            selection = self.time_select.values[0]

            if selection == "custom":
                modal = CustomTimeModal(
                    self.bot, self.guild_id, self.game, self.gamemode,
                    self.tier, self.role_id, original_view=self
                )
                await interaction.response.send_modal(modal)
                return

            await interaction.response.defer()

            eastern = pytz.timezone('America/New_York')
            now = datetime.now(eastern)

            if selection == "30min":
                self.selected_time = now + timedelta(minutes=30)
            elif selection == "1hour":
                self.selected_time = now + timedelta(hours=1)
            elif selection == "2hour":
                self.selected_time = now + timedelta(hours=2)
            elif selection == "tonight":
                tonight = now.replace(hour=20, minute=0, second=0, microsecond=0)
                if tonight <= now: tonight += timedelta(days=1)
                self.selected_time = tonight

            player_view = PlayerCountSelectView(
                self.bot, self.guild_id, self.game, self.gamemode,
                self.tier, self.selected_time, self.role_id
            )

            embed = discord.Embed(
                title="👥 최대 플레이어 수 선택",
                description=f"**게임:** {self.game}\n**모드:** {self.gamemode}\n**티어:** {self.tier}\n**시작 시간:** {self.selected_time.strftime('%Y-%m-%d %H:%M EST')}\n\n최대 플레이어 수를 선택하세요:",
                color=discord.Color.purple()
            )

            await interaction.edit_original_response(embed=embed, view=player_view)
            player_view.message = await interaction.original_response()

        except Exception as e:
            self.logger.error(f"Time selection error: {traceback.format_exc()}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"⚠ 오류가 발생했습니다: {str(e)}", ephemeral=True)
                else:
                    await interaction.followup.send(f"⚠ 오류가 발생했습니다: {str(e)}", ephemeral=True)
            except:
                pass

    async def back_to_tier_selection(self, interaction: discord.Interaction):
        """티어 선택으로 돌아가기"""
        try:
            await interaction.response.defer()
            tier_view = TierSelectView(self.bot, self.guild_id, self.game, self.gamemode, self.role_id)
            embed = discord.Embed(
                title="🏆 티어 범위 선택",
                description=f"**게임:** {self.game}\n**모드:** {self.gamemode}\n\n티어 범위를 선택하세요:",
                color=discord.Color.gold()
            )
            await interaction.edit_original_response(embed=embed, view=tier_view)
            tier_view.message = await interaction.original_response()
        except Exception as e:
            self.logger.error(f"Back to tier selection error: {traceback.format_exc()}")
            try:
                await interaction.followup.send(f"⚠ 오류가 발생했습니다: {str(e)}", ephemeral=True)
            except:
                pass


class CustomTimeModal(discord.ui.Modal, title="사용자 지정 시간 입력"):
    def __init__(self, bot, guild_id: int, game: str, gamemode: str, tier: str, role_id: int,
                 original_view: TimeSelectView):
        super().__init__()
        self.bot = bot
        self.guild_id = guild_id
        self.game = game
        self.gamemode = gamemode
        self.tier = tier
        self.role_id = role_id
        self.original_view = original_view
        self.logger = get_logger("내부 매치")

        # Updated placeholder to include timezone
        self.time_input = discord.ui.TextInput(
            label="시간 입력 (예: 22:00 EST 또는 30분 후)",
            style=discord.TextStyle.short,
            placeholder="HH:MM TZ (예: 21:30 PST) 또는 X분 후",
            required=True
        )
        self.add_item(self.time_input)

    async def on_submit(self, interaction: discord.Interaction):
        # We don't need to define the timezone here anymore, the parser will handle it.
        try:
            # Pass the default timezone to the parser
            parsed_time = await self.parse_time_input(self.time_input.value, default_tz_str='America/New_York')
            if not parsed_time:
                await interaction.response.send_message("⚠ 잘못된 시간 형식입니다. `HH:MM TZ` 또는 `X분 후` 형식으로 시도해주세요.",
                                                        ephemeral=True)
                return

            # The parsed_time is already timezone-aware, so we get the current time in UTC for a safe comparison.
            if parsed_time <= datetime.now(pytz.utc):
                await interaction.response.send_message("⚠ 시작 시간은 미래여야 합니다. (이미 지난 시간으로 설정된 것 같습니다)", ephemeral=True)
                return

            await interaction.response.defer()

            if self.original_view and self.original_view.message:
                player_view = PlayerCountSelectView(
                    self.bot, self.guild_id, self.game, self.gamemode,
                    self.tier, parsed_time, self.role_id
                )

                # Display the time in EST for consistency in the message
                est_time = parsed_time.astimezone(pytz.timezone('America/New_York'))

                embed = discord.Embed(
                    title="👥 최대 플레이어 수 선택",
                    description=f"**게임:** {self.game}\n**모드:** {self.gamemode}\n**티어:** {self.tier}\n**시작 시간:** {est_time.strftime('%Y-%m-%d %H:%M EST')}\n\n최대 플레이어 수를 선택하세요:",
                    color=discord.Color.purple()
                )
                await self.original_view.message.edit(embed=embed, view=player_view)
                player_view.message = self.original_view.message
            else:
                await interaction.followup.send("⚠ 원본 메시지를 찾을 수 없어 계속할 수 없습니다. 다시 시도해주세요.", ephemeral=True)

        except Exception as e:
            self.logger.error(f"Custom time submit error: {traceback.format_exc()}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"⚠ 시간 처리 중 오류가 발생했습니다.", ephemeral=True)
            else:
                await interaction.followup.send(f"⚠ 시간 처리 중 오류가 발생했습니다.", ephemeral=True)

    async def parse_time_input(self, input_str: str, default_tz_str: str) -> Optional[datetime]:
        """
        Parses flexible time formats including timezones:
        1. 'X분 후' (relative time)
        2. 'HH:MM TZ' (e.g., '21:30 PST')
        3. 'HH:MM' (assumes default timezone)
        """
        input_str = input_str.strip()

        # Handle 'X분 후' first as it's unambiguous
        if '분 후' in input_str:
            try:
                minutes_str = input_str.split('분 후')[0]
                minutes = int(minutes_str)
                # Relative time is always based on the current moment, timezone aware
                return datetime.now(pytz.utc) + timedelta(minutes=minutes)
            except (ValueError, IndexError):
                return None

        # Map common TZ abbreviations to IANA names to handle DST correctly
        tz_map = {
            'est': 'America/New_York', 'edt': 'America/New_York',
            'cst': 'America/Chicago', 'cdt': 'America/Chicago',
            'pst': 'America/Los_Angeles', 'pdt': 'America/Los_Angeles',
        }

        parts = input_str.rsplit(' ', 1)
        time_str = input_str
        target_tz_str = default_tz_str  # Default timezone

        # Check if the last part of the string is a recognized timezone
        if len(parts) > 1 and parts[1].lower() in tz_map:
            time_str = parts[0]
            target_tz_str = tz_map[parts[1].lower()]

        try:
            target_tz = pytz.timezone(target_tz_str)
            now_in_target_tz = datetime.now(target_tz)

            time_obj = datetime.strptime(time_str, '%H:%M').time()

            # Combine with today's date in the target timezone
            potential_dt = now_in_target_tz.replace(
                hour=time_obj.hour, minute=time_obj.minute, second=0, microsecond=0
            )

            # FIXED: More lenient check - only add a day if the time is more than 1 hour in the past
            # This prevents issues with small time differences and timezone conversions
            if potential_dt <= now_in_target_tz - timedelta(hours=1):
                potential_dt += timedelta(days=1)

            return potential_dt
        except (ValueError, pytz.UnknownTimeZoneError):
            return None  # Return None if parsing fails
class PlayerCountSelectView(discord.ui.View):
    """플레이어 수 선택 뷰"""

    def __init__(self, bot, guild_id: int, game: str, gamemode: str, tier: str, start_time: datetime, role_id: int):
        super().__init__(timeout=900)
        self.bot = bot
        self.guild_id = guild_id
        self.game = game
        self.gamemode = gamemode
        self.tier = tier
        self.start_time = start_time
        self.role_id = role_id
        self.selected_max_players = None
        self.logger = get_logger("내부 매치")
        self.message = None

        player_options = [
            discord.SelectOption(label="10명", value="10", emoji="👥"),
            discord.SelectOption(label="20명", value="20", emoji="👥"),
            discord.SelectOption(label="30명", value="30", emoji="👥"),
            discord.SelectOption(label="사용자 지정", value="custom", emoji="⚙️")
        ]

        self.player_select = discord.ui.Select(placeholder="최대 플레이어 수 선택...", options=player_options,
                                               custom_id="player_select")
        self.player_select.callback = self.player_selected
        self.add_item(self.player_select)

        back_button = discord.ui.Button(label="뒤로", style=discord.ButtonStyle.secondary, emoji="⬅️")
        back_button.callback = self.back_to_time_selection
        self.add_item(back_button)

    async def on_timeout(self):
        """Handle view timeout"""
        try:
            for item in self.children:
                item.disabled = True
            if self.message:
                embed = discord.Embed(
                    title="⏱️ 시간 초과",
                    description="이 메뉴가 만료되었습니다. 새로운 내전 생성을 시작해주세요.",
                    color=discord.Color.red()
                )
                await self.message.edit(embed=embed, view=self)
        except Exception as e:
            self.logger.error(f"Timeout error in PlayerCountSelectView: {traceback.format_exc()}")

    async def player_selected(self, interaction: discord.Interaction):
        """플레이어 수 선택 처리"""
        try:
            selection = self.player_select.values[0]

            if selection == "custom":
                modal = CustomPlayerCountModal(
                    self.bot, self.guild_id, self.game, self.gamemode,
                    self.tier, self.start_time, self.role_id, original_view=self
                )
                await interaction.response.send_modal(modal)
                return

            # Defer here since we are about to do work
            await interaction.response.defer(ephemeral=True)
            self.selected_max_players = int(selection)
            await self.finalize_scrim_creation(interaction, self.selected_max_players)

        except Exception as e:
            self.logger.error(f"Player selection error: {traceback.format_exc()}")
            try:
                await interaction.followup.send(f"⚠ 오류가 발생했습니다: {str(e)}", ephemeral=True)
            except:
                pass

    async def finalize_scrim_creation(self, interaction: discord.Interaction, max_players: int):
        """Handles the actual scrim creation logic and user feedback."""
        try:
            # Ensure the interaction is deferred if it hasn't been already.
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)

            scrim_cog = self.bot.get_cog('ScrimCog')
            if not scrim_cog:
                await interaction.followup.send("❌ 내전 시스템을 찾을 수 없습니다.", ephemeral=True)
                return

            scrim_id = await scrim_cog.create_scrim(
                guild_id=self.guild_id,
                organizer_id=interaction.user.id,
                game=self.game,
                gamemode=self.gamemode,
                tier_range=self.tier,
                start_time=self.start_time,
                max_players=max_players,
                channel_id=interaction.channel_id
            )

            if scrim_id:
                # Disable the view on the original ephemeral message
                if self.message:
                    await self.message.edit(content="✅ 내전이 성공적으로 생성되었습니다!", embed=None, view=None)
                await interaction.followup.send("✅ 내전이 생성되었습니다! 채널에 곧 게시됩니다.", ephemeral=True)

                # Heavy lifting in a background task
                asyncio.create_task(self.post_scrim_and_notify_safe(scrim_cog, scrim_id))
            else:
                await interaction.followup.send("❌ 내전 생성 중 오류가 발생했습니다. 로그를 확인해주세요.", ephemeral=True)

        except Exception as e:
            self.logger.error(f"Finalize scrim error: {traceback.format_exc()}")
            try:
                await interaction.followup.send("❌ 내전 생성 중 심각한 오류가 발생했습니다.", ephemeral=True)
            except:
                pass

    async def post_scrim_and_notify_safe(self, scrim_cog, scrim_id):
        """Safe background task that won't affect interaction timing"""
        try:
            await asyncio.sleep(0.1)  # Small delay to ensure interaction completes

            # Get scrim data
            scrim_data = scrim_cog.scrims_data.get(scrim_id)
            if not scrim_data: return

            guild = self.bot.get_guild(scrim_data['guild_id'])
            if not guild: return

            channel = guild.get_channel(scrim_data['channel_id'])
            if not channel: return

            # Post the main scrim message
            await scrim_cog.post_scrim_message(channel, scrim_id)

            # Send role notification if role_id is set
            if self.role_id:
                role = guild.get_role(self.role_id)
                if role:
                    try:
                        mention_msg = await channel.send(f"{role.mention} 새로운 내전이 생성되었습니다!")
                        await asyncio.sleep(5)
                        await mention_msg.delete()
                    except Exception as e:
                        self.logger.warning(f"Failed to send or delete role mention for scrim {scrim_id}: {e}")

        except Exception as e:
            self.logger.error(f"Background notification error: {traceback.format_exc()}")

    async def back_to_time_selection(self, interaction: discord.Interaction):
        """시간 선택으로 돌아가기"""
        try:
            await interaction.response.defer()
            time_view = TimeSelectView(self.bot, self.guild_id, self.game, self.gamemode, self.tier, self.role_id)
            embed = discord.Embed(
                title="⏰ 시작 시간 선택",
                description=f"**게임:** {self.game}\n**모드:** {self.gamemode}\n**티어:** {self.tier}\n\n내전은 언제 시작해야 하나요?",
                color=discord.Color.orange()
            )
            await interaction.edit_original_response(embed=embed, view=time_view)
            time_view.message = await interaction.original_response()
        except Exception as e:
            self.logger.error(f"Back to time selection error: {traceback.format_exc()}")
            try:
                await interaction.followup.send(f"⚠ 오류가 발생했습니다: {str(e)}", ephemeral=True)
            except:
                pass


class CustomPlayerCountModal(discord.ui.Modal, title="사용자 지정 플레이어 수 입력"):
    def __init__(self, bot, guild_id: int, game: str, gamemode: str, tier: str, start_time: datetime, role_id: int,
                 original_view: PlayerCountSelectView):
        super().__init__()
        self.bot = bot
        self.guild_id = guild_id
        self.game = game
        self.gamemode = gamemode
        self.tier = tier
        self.start_time = start_time
        self.role_id = role_id
        self.original_view = original_view
        self.logger = get_logger("내부 매치")

        self.player_input = discord.ui.TextInput(
            label="최대 플레이어 수 입력 (2-50)",
            style=discord.TextStyle.short,
            placeholder="숫자만 입력",
            required=True
        )
        self.add_item(self.player_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            max_players = int(self.player_input.value)
            if not (2 <= max_players <= 50):
                await interaction.response.send_message("⚠ 플레이어 수는 2에서 50 사이여야 합니다.", ephemeral=True)
                return

            # Defer the modal interaction
            await interaction.response.defer(ephemeral=True)

            if self.original_view:
                # Call the finalization logic from the original view
                await self.original_view.finalize_scrim_creation(interaction, max_players)
                # DO NOT send another followup here, as finalize_scrim_creation already does.
            else:
                await interaction.followup.send("⚠ 원본 뷰를 찾을 수 없어 내전을 생성할 수 없습니다.", ephemeral=True)

        except ValueError:
            await interaction.response.send_message("⚠ 유효한 숫자를 입력해주세요.", ephemeral=True)
        except Exception as e:
            self.logger.error(f"Custom player count submit error: {traceback.format_exc()}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"⚠ 플레이어 수 처리 중 오류가 발생했습니다.", ephemeral=True)
            else:
                await interaction.followup.send(f"⚠ 플레이어 수 처리 중 오류가 발생했습니다.", ephemeral=True)


class MapPoolModal(discord.ui.Modal):
    """맵 풀 관리를 위한 모달"""

    def __init__(self, bot, guild_id: int, current_maps: List[str]):
        super().__init__(title="맵 풀 설정", timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.logger = get_logger("내부 매치")

        current_maps_str = ", ".join(current_maps)
        if len(current_maps_str) > 4000:
            current_maps_str = current_maps_str[:3990] + "..."

        self.map_input = discord.ui.TextInput(
            label="맵 목록 (쉼표로 구분)",
            placeholder="예: 바인드, 헤이븐, 스플릿, 어센트...",
            default=current_maps_str,
            required=True,
            style=discord.TextStyle.paragraph
        )
        self.add_item(self.map_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            map_list = [map_name.strip() for map_name in self.map_input.value.split(',') if map_name.strip()]
            if len(map_list) < 2:
                await interaction.response.send_message("❌ 최소 2개의 맵이 필요합니다.", ephemeral=True)
                return

            scrim_cog = self.bot.get_cog('ScrimCog')
            if scrim_cog:
                success = await scrim_cog.update_map_pool(self.guild_id, map_list)
                if success:
                    map_list_str = ', '.join(map_list)
                    if len(map_list_str) > 1500:
                        map_list_str = map_list_str[:1500] + "... (목록이 너무 길어 일부만 표시)"
                    await interaction.response.send_message(
                        f"✅ 맵 풀이 성공적으로 업데이트되었습니다!\n**총 {len(map_list)} 맵**: {map_list_str}",
                        ephemeral=True
                    )
                else:
                    await interaction.response.send_message("❌ 맵 풀 업데이트 중 오류가 발생했습니다.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ 내전 시스템을 찾을 수 없습니다.", ephemeral=True)

        except Exception as e:
            self.logger.error(f"Map pool modal error for guild {self.guild_id}: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ 오류가 발생했습니다. 다시 시도해주세요.", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        self.logger.error(f"Modal error in guild {self.guild_id}: {error}", exc_info=True)
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ 오류가 발생했습니다. 다시 시도해주세요.", ephemeral=True)


class ScrimView(discord.ui.View):
    """버튼 스타일이 개선된 내전 뷰"""

    def __init__(self, bot, scrim_id: str):
        super().__init__(timeout=None)
        self.bot = bot
        self.scrim_id = scrim_id
        self.logger = get_logger("내부 매치")
        # Defer getting scrim_data to the interaction time to ensure it's fresh
        self.update_button_states()

    def update_button_states(self):
        """현재 내전 상태에 따라 버튼 상태 업데이트"""
        # This method is less reliable for persistent views as scrim_data isn't stored.
        # Logic will be handled within each button press instead.
        pass

    async def _get_scrim_cog_and_data(self, interaction: discord.Interaction) -> tuple[
        Optional['ScrimCog'], Optional[Dict]]:
        """Helper to get fresh cog and scrim data, and handle errors."""
        scrim_cog = self.bot.get_cog('ScrimCog')
        if not scrim_cog:
            await interaction.followup.send("❌ 내전 시스템을 찾을 수 없습니다.", ephemeral=True)
            return None, None

        scrim_data = scrim_cog.scrims_data.get(self.scrim_id)
        if not scrim_data:
            await interaction.followup.send("❌ 이 내전을 더 이상 찾을 수 없습니다. 만료되었을 수 있습니다.", ephemeral=True)
            # Optionally disable the view
            self.stop()
            await interaction.message.edit(view=self)
            return None, None

        return scrim_cog, scrim_data

    def _check_if_locked(self, scrim_data: Dict) -> bool:
        """Check if the scrim is within the 30-minute lock window."""
        eastern = pytz.timezone('America/New_York')
        now = datetime.now(eastern)

        start_time = scrim_data['start_time']
        # Ensure start_time is in Eastern timezone for comparison
        if start_time.tzinfo == pytz.utc:
            start_time = start_time.astimezone(eastern)
        elif start_time.tzinfo is None:
            start_time = pytz.utc.localize(start_time).astimezone(eastern)
        elif start_time.tzinfo != eastern:
            start_time = start_time.astimezone(eastern)

        return start_time - now <= timedelta(minutes=30)

    @discord.ui.button(label="참가", style=discord.ButtonStyle.success, custom_id="join_scrim", emoji="✅")
    async def join_scrim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        scrim_cog, scrim_data = await self._get_scrim_cog_and_data(interaction)
        if not scrim_cog or not scrim_data: return

        if self._check_if_locked(scrim_data):
            await interaction.followup.send("❌ 내전 시작 30분 전에는 참가할 수 없습니다.", ephemeral=True)
            return

        success, message = await scrim_cog.join_scrim(interaction.user.id, self.scrim_id)
        await interaction.followup.send(message, ephemeral=True)
        if success:
            asyncio.create_task(scrim_cog.update_scrim_message(interaction.message, self.scrim_id))

    @discord.ui.button(label="나가기", style=discord.ButtonStyle.danger, custom_id="leave_scrim", emoji="❌")
    async def leave_scrim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        scrim_cog, scrim_data = await self._get_scrim_cog_and_data(interaction)
        if not scrim_cog or not scrim_data: return

        if self._check_if_locked(scrim_data):
            await interaction.followup.send("❌ 내전 시작 30분 전에는 나갈 수 없습니다.", ephemeral=True)
            return

        success, message = await scrim_cog.leave_scrim(interaction.user.id, self.scrim_id)
        await interaction.followup.send(message, ephemeral=True)
        if success:
            asyncio.create_task(scrim_cog.update_scrim_message(interaction.message, self.scrim_id))

    @discord.ui.button(label="대기열 참가", style=discord.ButtonStyle.secondary, custom_id="join_queue", emoji="⏳")
    async def join_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        scrim_cog, scrim_data = await self._get_scrim_cog_and_data(interaction)
        if not scrim_cog or not scrim_data: return

        if self._check_if_locked(scrim_data):
            await interaction.followup.send("❌ 내전 시작 30분 전에는 대기열에 참가할 수 없습니다.", ephemeral=True)
            return

        success, message = await scrim_cog.join_queue(interaction.user.id, self.scrim_id)
        await interaction.followup.send(message, ephemeral=True)
        if success:
            asyncio.create_task(scrim_cog.update_scrim_message(interaction.message, self.scrim_id))

    @discord.ui.button(label="대기열 나가기", style=discord.ButtonStyle.secondary, custom_id="leave_queue", emoji="🚪")
    async def leave_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        scrim_cog, scrim_data = await self._get_scrim_cog_and_data(interaction)
        if not scrim_cog or not scrim_data: return

        if self._check_if_locked(scrim_data):
            await interaction.followup.send("❌ 내전 시작 30분 전에는 대기열에서 나갈 수 없습니다.", ephemeral=True)
            return

        success, message = await scrim_cog.leave_queue(interaction.user.id, self.scrim_id)
        await interaction.followup.send(message, ephemeral=True)
        if success:
            asyncio.create_task(scrim_cog.update_scrim_message(interaction.message, self.scrim_id))

    @discord.ui.button(label="취소", style=discord.ButtonStyle.danger, custom_id="cancel_scrim", emoji="🗑️")
    async def cancel_scrim(self, interaction: discord.Interaction, button: discord.ui.Button):
        # We must defer later after permission checks
        scrim_cog = self.bot.get_cog('ScrimCog')
        if not scrim_cog:
            await interaction.response.send_message("❌ 내전 시스템을 찾을 수 없습니다.", ephemeral=True)
            return

        scrim_data = scrim_cog.scrims_data.get(self.scrim_id)
        if not scrim_data:
            await interaction.response.send_message("❌ 이 내전을 더 이상 찾을 수 없습니다.", ephemeral=True)
            return

        is_organizer = interaction.user.id == scrim_data['organizer_id']
        is_staff = scrim_cog.has_staff_permissions(interaction.user)

        if not (is_organizer or is_staff):
            await interaction.response.send_message("❌ 이 내전을 취소할 권한이 없습니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        embed = discord.Embed(
            title="⚠️ 내전 취소 확인",
            description="이 내전을 정말 취소하시겠습니까?\n모든 참가자에게 알림이 전송됩니다.",
            color=discord.Color.red()
        )

        view = discord.ui.View(timeout=60)
        confirm_button = discord.ui.Button(label="확인", style=discord.ButtonStyle.danger)
        cancel_button = discord.ui.Button(label="취소", style=discord.ButtonStyle.secondary)

        async def confirm_callback(confirm_interaction: discord.Interaction):
            await confirm_interaction.response.defer(ephemeral=True)
            success = await scrim_cog.cancel_scrim(self.scrim_id, interaction.user.id)
            if success:
                await confirm_interaction.followup.send("✅ 내전이 취소되었습니다.", ephemeral=True)
                asyncio.create_task(scrim_cog.update_scrim_message(interaction.message, self.scrim_id))
            else:
                await confirm_interaction.followup.send("❌ 내전 취소 중 오류가 발생했습니다.", ephemeral=True)

        async def cancel_callback(cancel_interaction: discord.Interaction):
            await cancel_interaction.response.edit_message(content="취소되었습니다.", embed=None, view=None)

        confirm_button.callback = confirm_callback
        cancel_button.callback = cancel_callback
        view.add_item(confirm_button)
        view.add_item(cancel_button)

        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class ScrimCreateView(discord.ui.View):
    """스타일이 개선된 지속적인 뷰"""

    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.logger = get_logger("내부 매치")

    @discord.ui.button(label="내전 생성", style=discord.ButtonStyle.primary, custom_id="create_scrim_persistent", emoji="🎮")
    async def create_scrim(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)

            if not config.is_feature_enabled(interaction.guild.id, 'scrim_system'):
                await interaction.followup.send("⚠ 이 서버에서 내전 시스템이 비활성화되어 있습니다.", ephemeral=True)
                return

            game_view = GameSelectView(self.bot, interaction.guild.id)
            embed = discord.Embed(
                title="🎮 게임 선택",
                description="내전을 위한 게임을 선택하세요:",
                color=discord.Color.green()
            ).set_footer(text="아래 드롭다운을 사용하여 게임을 선택하세요")

            # followup.send returns the message, which we need for the view.
            message = await interaction.followup.send(embed=embed, view=game_view, ephemeral=True)
            game_view.message = message

        except Exception as e:
            self.logger.error(f"Create scrim button error: {e}", exc_info=True)
            try:
                await interaction.followup.send("⚠ 오류가 발생했습니다.", ephemeral=True)
            except:
                pass


class ScrimCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("내부 매치")
        self.scrims_data: Dict[str, Dict] = {}
        self.scrims_file = "data/scrims.json"
        self.map_pools_file = "data/map_pools.json"
        self.map_pools: Dict[int, List[str]] = {}
        self.default_valorant_maps = [
            "바인드", "헤이븐", "스플릿", "어센트", "아이스박스",
            "브리즈", "프랙처", "펄", "로터스", "선셋", "어비스"
        ]
        self.bot.loop.create_task(self.after_bot_ready())

    async def after_bot_ready(self):
        """Waits for the bot to be ready before starting tasks."""
        await self.bot.wait_until_ready()
        await self.load_scrims_data()
        # await self.migrate_timezone_data()  # Add this line
        await self.load_map_pools()
        self.setup_persistent_views()
        await self.setup_scrim_panels()
        self.scrim_notifications.start()
        self.cleanup_old_scrims.start()

    def setup_persistent_views(self):
        """Setup persistent views on bot startup"""
        try:
            self.bot.add_view(ScrimCreateView(self.bot))
            for scrim_id, scrim_data in self.scrims_data.items():
                if scrim_data['status'] == '활성':
                    # Pass only the ID to reduce memory and ensure data is fresh
                    self.bot.add_view(ScrimView(self.bot, scrim_id))
            self.logger.info("Persistent views setup completed.")
        except Exception as e:
            self.logger.error(f"Error setting up persistent views: {e}", exc_info=True)

    def has_staff_permissions(self, member: discord.Member) -> bool:
        """Checks if a member has staff permissions."""
        if member.guild_permissions.administrator: return True
        admin_role_id = config.get_role_id(member.guild.id, 'admin_role')
        if admin_role_id and discord.utils.get(member.roles, id=admin_role_id): return True
        staff_role_id = config.get_role_id(member.guild.id, 'staff_role')
        if staff_role_id and discord.utils.get(member.roles, id=staff_role_id): return True
        return False

    async def load_scrims_data(self):
        try:
            if os.path.exists(self.scrims_file):
                with open(self.scrims_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                    for scrim_id, scrim_data in data.items():
                        # Parse datetime strings and keep them as UTC
                        start_time_str = scrim_data['start_time']
                        created_at_str = scrim_data['created_at']

                        start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                        created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))

                        # Ensure they're UTC timezone aware
                        if start_time.tzinfo is None:
                            start_time = start_time.replace(tzinfo=pytz.UTC)
                        if created_at.tzinfo is None:
                            created_at = created_at.replace(tzinfo=pytz.UTC)

                        scrim_data['start_time'] = start_time
                        scrim_data['created_at'] = created_at

                    self.scrims_data = data
                self.logger.info("Successfully loaded scrims data.")
        except Exception as e:
            self.logger.error(f"Error loading scrims data: {e}", exc_info=True)
    async def save_scrims_data(self):
        """Saves scrims data to file asynchronously."""
        try:
            os.makedirs(os.path.dirname(self.scrims_file), exist_ok=True)
            data_to_save = {}

            for scrim_id, scrim_data in self.scrims_data.items():
                data_copy = scrim_data.copy()

                # Convert timezone-aware datetimes to UTC for storage
                start_time = data_copy['start_time']
                if start_time.tzinfo is None:
                    # If somehow no timezone, assume it's Eastern and convert to UTC
                    eastern = pytz.timezone('America/New_York')
                    start_time = eastern.localize(start_time)
                # Convert to UTC and store as ISO string
                data_copy['start_time'] = start_time.astimezone(pytz.utc).isoformat()

                created_at = data_copy['created_at']
                if created_at.tzinfo is None:
                    eastern = pytz.timezone('America/New_York')
                    created_at = eastern.localize(created_at)
                data_copy['created_at'] = created_at.astimezone(pytz.utc).isoformat()

                data_to_save[scrim_id] = data_copy

            def write_file():
                with open(self.scrims_file, 'w', encoding='utf-8') as f:
                    json.dump(data_to_save, f, ensure_ascii=False, indent=2)

            await asyncio.to_thread(write_file)
        except Exception as e:
            self.logger.error(f"Error saving scrims data: {e}", exc_info=True)

    async def load_map_pools(self):
        try:
            if os.path.exists(self.map_pools_file):
                with open(self.map_pools_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.map_pools = {int(k): v for k, v in data.items()}
                self.logger.info("Successfully loaded map pools data.")
        except Exception as e:
            self.logger.error(f"Error loading map pools: {e}", exc_info=True)
            self.map_pools = {}

    async def save_map_pools(self):
        try:
            os.makedirs(os.path.dirname(self.map_pools_file), exist_ok=True)
            with open(self.map_pools_file, 'w', encoding='utf-8') as f:
                json.dump(self.map_pools, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"Error saving map pools: {e}", exc_info=True)

    def get_map_pool(self, guild_id: int) -> List[str]:
        return self.map_pools.get(guild_id, self.default_valorant_maps.copy())

    async def update_map_pool(self, guild_id: int, maps: List[str]) -> bool:
        try:
            self.map_pools[guild_id] = maps
            await self.save_map_pools()
            self.logger.info(f"Updated map pool for guild {guild_id}.")
            return True
        except Exception as e:
            self.logger.error(f"Error updating map pool for guild {guild_id}: {e}", exc_info=True)
            return False

    async def setup_scrim_panels(self):
        """Sets up the scrim creation panel in configured channels."""
        all_configs = config.get_all_server_configs()
        for guild_id_str, guild_config in all_configs.items():
            if guild_config.get('features', {}).get('scrim_system'):
                guild_id = int(guild_id_str)
                channel_id = config.get_channel_id(guild_id, 'scrim_channel')
                if channel_id:
                    channel = self.bot.get_channel(channel_id)
                    if channel: await self.setup_scrim_panel(channel)

    async def setup_scrim_panel(self, channel: discord.TextChannel):
        """Ensures a scrim creation panel exists in a specific channel."""
        try:
            async for message in channel.history(limit=50):
                if message.author == self.bot.user and message.embeds and "내전 생성 패널" in message.embeds[0].title:
                    # Found an existing panel, ensure view is correct
                    await message.edit(view=ScrimCreateView(self.bot))
                    self.logger.info(f"Refreshed existing scrim panel in #{channel.name}.")
                    return

            # No panel found, create a new one
            embed = self.create_scrim_panel_embed()
            await channel.send(embed=embed, view=ScrimCreateView(self.bot))
            self.logger.info(f"Created new scrim panel in #{channel.name}.")

        except Exception as e:
            self.logger.error(f"Error setting up scrim panel in #{channel.name}: {e}", exc_info=True)

    def create_scrim_panel_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🎮 내전 생성 패널",
            description=(
                "**개선된 내전 시스템**에 오신 것을 환영합니다! 아래 버튼을 클릭하여 새 내전을 생성하세요.\n\n"
                "**✨ 기능:**\n"
                "• 역할 태그와 함께 쉬운 게임 선택\n"
                "• 빠른 시간 선택 및 사용자 지정 시간\n"
                "• 티어 범위 선택\n"
                "• 간소화된 플레이어 수 설정\n\n"
                "**🎯 지원되는 게임:**\n"
                "• 발로란트 • 리그 오브 레전드 • 팀파이트 택틱스\n"
                "• 배틀그라운드 • 기타 게임"
            ),
            color=discord.Color.blue()
        ).set_footer(text="개선된 내전 시스템 v2.1 • 시작하려면 버튼을 클릭하세요!")
        return embed

    # FIXED: This method now correctly accepts parameters instead of using `self`.
    async def create_scrim(self, guild_id: int, organizer_id: int, game: str, gamemode: str, tier_range: str,
                           start_time: datetime, max_players: int, channel_id: int) -> Optional[str]:
        """Creates a new scrim, saves it, and returns its ID."""
        try:
            scrim_id = str(random.randint(100000, 999999))
            while scrim_id in self.scrims_data:
                scrim_id = str(random.randint(100000, 999999))

            scrim_data = {
                'id': scrim_id,
                'guild_id': guild_id,
                'organizer_id': organizer_id,
                'game': game,
                'gamemode': gamemode,
                'tier_range': tier_range,
                'start_time': start_time,
                'max_players': max_players,
                'channel_id': channel_id,
                'participants': [organizer_id],  # Organizer automatically joins
                'queue': [],
                'status': '활성',
                'created_at': datetime.now(pytz.timezone('America/New_York')),
                # FIXED: Added this key to prevent KeyError in the notification task.
                'notifications_sent': {'10min': False, '2min': False},
                'message_id': None
            }
            self.scrims_data[scrim_id] = scrim_data
            await self.save_scrims_data()
            self.logger.info(f"New scrim created: {scrim_id} in guild {guild_id}")
            return scrim_id
        except Exception as e:
            self.logger.error(f"Error in ScrimCog.create_scrim: {e}", exc_info=True)
            return None

    async def post_scrim_message(self, channel: discord.TextChannel, scrim_id: str):
        """Posts the interactive scrim message to the channel."""
        try:
            scrim_data = self.scrims_data.get(scrim_id)
            if not scrim_data: return

            embed = self.create_scrim_embed(scrim_data)
            view = ScrimView(self.bot, scrim_id)
            message = await channel.send(embed=embed, view=view)

            scrim_data['message_id'] = message.id
            await self.save_scrims_data()
            self.logger.info(f"Posted message for scrim {scrim_id} in #{channel.name}")

        except Exception as e:
            self.logger.error(f"Error posting scrim message {scrim_id}: {e}", exc_info=True)

    def create_scrim_embed(self, scrim_data: Dict) -> discord.Embed:
        eastern = pytz.timezone('America/New_York')
        now = datetime.now(eastern)

        # Get the start time and ensure it's in Eastern timezone for display
        start_time = scrim_data['start_time']

        # Convert UTC time to Eastern for display
        if start_time.tzinfo == pytz.utc:
            start_time = start_time.astimezone(eastern)
        elif start_time.tzinfo is None:
            # If no timezone info, assume UTC and convert
            start_time = pytz.utc.localize(start_time).astimezone(eastern)
        elif start_time.tzinfo != eastern:
            # Convert any other timezone to Eastern
            start_time = start_time.astimezone(eastern)

        # Rest of the embed creation logic...
        status_colors = {'활성': discord.Color.green(), '취소됨': discord.Color.red(), '완료됨': discord.Color.blue()}
        status_emojis = {'활성': '🟢', '취소됨': '🔴', '완료됨': '🔵'}
        game_emojis = {'발로란트': '🎯', '리그 오브 레전드': '⚔️', '팀파이트 택틱스': '♟️', '배틀그라운드': '🔫', '기타 게임': '🎮'}

        color = status_colors.get(scrim_data['status'], discord.Color.default())
        status_emoji = status_emojis.get(scrim_data['status'], '❓')
        game_emoji = game_emojis.get(scrim_data['game'], '🎮')

        embed = discord.Embed(
            title=f"{game_emoji} {scrim_data['game']} 내전",
            color=color,
            timestamp=now
        )

        time_until_start = start_time - now
        time_text = ""
        if scrim_data['status'] == '활성' and time_until_start.total_seconds() > 0:
            hours, rem = divmod(int(time_until_start.total_seconds()), 3600)
            mins, _ = divmod(rem, 60)
            if hours > 0:
                time_text = f" • {hours}시간 {mins}분 후 시작"
            else:
                time_text = f" • {mins}분 후 시작"

        status_text = f"{status_emoji} {scrim_data['status']}"
        p_count = len(scrim_data['participants'])
        max_p = scrim_data['max_players']

        embed.description = (
            f"**모드:** {scrim_data['gamemode']}\n"
            f"**티어:** {scrim_data['tier_range']}\n"
            f"**시작:** <t:{int(start_time.timestamp())}:F>{time_text}\n"
            f"**상태:** {status_text}\n"
            f"**플레이어:** {p_count}/{max_p}"
            f"{' ✅' if p_count >= max_p else ''}"
            f" • **대기열:** {len(scrim_data['queue'])}"
        )

        # Rest of the method remains the same...
        guild = self.bot.get_guild(scrim_data['guild_id'])
        if guild:
            organizer = guild.get_member(scrim_data['organizer_id'])
            embed.add_field(name="👑 주최자",
                            value=organizer.display_name if organizer else f"ID: {scrim_data['organizer_id']}",
                            inline=True)

            if scrim_data['participants']:
                p_names = [f"`{i + 1}.` {guild.get_member(uid).display_name if guild.get_member(uid) else f'ID: {uid}'}"
                           for i, uid in enumerate(scrim_data['participants'])]
                embed.add_field(name="📋 참가자", value="\n".join(p_names), inline=False)

            if scrim_data['queue']:
                q_names = [f"`{i + 1}.` {guild.get_member(uid).display_name if guild.get_member(uid) else f'ID: {uid}'}"
                           for i, uid in enumerate(scrim_data['queue'])]
                embed.add_field(name="⏳ 대기열", value="\n".join(q_names), inline=False)

        if scrim_data['status'] == '취소됨':
            embed.add_field(name="⚠️ 공지", value="이 내전은 취소되었습니다.", inline=False)

        embed.set_footer(text=f"내전 ID: {scrim_data['id']} • 개선된 내전 시스템 v2.1")
        return embed

    async def join_scrim(self, user_id: int, scrim_id: str) -> tuple[bool, str]:
        scrim_data = self.scrims_data.get(scrim_id)
        if not scrim_data: return False, "❌ 내전을 찾을 수 없습니다."
        if scrim_data['status'] != '활성': return False, "❌ 이 내전은 더 이상 활성 상태가 아닙니다."
        if user_id in scrim_data['participants']: return False, "❌ 이미 참가 중입니다."
        if len(scrim_data['participants']) >= scrim_data['max_players']: return False, "❌ 내전이 꽉 찼습니다. 대기열에 참가해주세요."

        if user_id in scrim_data['queue']: scrim_data['queue'].remove(user_id)
        scrim_data['participants'].append(user_id)
        await self.save_scrims_data()
        self.logger.info(f"User {user_id} joined scrim {scrim_id}.")
        return True, "✅ 내전에 성공적으로 참가했습니다!"

    async def leave_scrim(self, user_id: int, scrim_id: str) -> tuple[bool, str]:
        scrim_data = self.scrims_data.get(scrim_id)
        if not scrim_data: return False, "❌ 내전을 찾을 수 없습니다."
        if user_id not in scrim_data['participants']: return False, "❌ 참가 중이 아닙니다."

        scrim_data['participants'].remove(user_id)

        if scrim_data['queue'] and len(scrim_data['participants']) < scrim_data['max_players']:
            next_user_id = scrim_data['queue'].pop(0)
            scrim_data['participants'].append(next_user_id)
            guild = self.bot.get_guild(scrim_data['guild_id'])
            if guild:
                member = guild.get_member(next_user_id)
                if member:
                    try:
                        await member.send(f"**{scrim_data['game']}** 내전에 자리가 생겨 대기열에서 자동으로 이동되었습니다!")
                    except discord.Forbidden:
                        pass  # Can't DM user

        await self.save_scrims_data()
        self.logger.info(f"User {user_id} left scrim {scrim_id}.")
        return True, "✅ 내전에서 성공적으로 나갔습니다."

    async def join_queue(self, user_id: int, scrim_id: str) -> tuple[bool, str]:
        scrim_data = self.scrims_data.get(scrim_id)
        if not scrim_data: return False, "❌ 내전을 찾을 수 없습니다."
        if scrim_data['status'] != '활성': return False, "❌ 이 내전은 더 이상 활성 상태가 아닙니다."
        if user_id in scrim_data['queue']: return False, "❌ 이미 대기열에 있습니다."
        if user_id in scrim_data['participants']: return False, "❌ 이미 참가 중입니다."
        if len(scrim_data['participants']) < scrim_data['max_players']: return False, "❌ 아직 자리가 남아 있습니다. 직접 참가해주세요."

        scrim_data['queue'].append(user_id)
        await self.save_scrims_data()
        self.logger.info(f"User {user_id} joined queue for scrim {scrim_id}.")
        return True, f"✅ 대기열에 성공적으로 가입했습니다! (현재 위치: {len(scrim_data['queue'])})"

    async def leave_queue(self, user_id: int, scrim_id: str) -> tuple[bool, str]:
        scrim_data = self.scrims_data.get(scrim_id)
        if not scrim_data: return False, "❌ 내전을 찾을 수 없습니다."
        if user_id not in scrim_data['queue']: return False, "❌ 대기열에 없습니다."

        scrim_data['queue'].remove(user_id)
        await self.save_scrims_data()
        self.logger.info(f"User {user_id} left queue for scrim {scrim_id}.")
        return True, "✅ 대기열에서 성공적으로 나갔습니다."

    async def cancel_scrim(self, scrim_id: str, canceller_id: int) -> bool:
        scrim_data = self.scrims_data.get(scrim_id)
        if not scrim_data: return False

        scrim_data['status'] = '취소됨'
        await self.save_scrims_data()

        guild = self.bot.get_guild(scrim_data['guild_id'])
        if guild:
            canceller = guild.get_member(canceller_id)
            canceller_name = canceller.display_name if canceller else "관리자"
            all_user_ids = set(scrim_data['participants'] + scrim_data['queue'])
            for user_id in all_user_ids:
                member = guild.get_member(user_id)
                if member:
                    try:
                        await member.send(f"**{scrim_data['game']}** 내전이 **{canceller_name}**에 의해 취소되었습니다.")
                    except discord.Forbidden:
                        pass

        self.logger.info(f"Scrim {scrim_id} cancelled by user {canceller_id}.")
        return True

    async def update_scrim_message(self, message: discord.Message, scrim_id: str):
        try:
            scrim_data = self.scrims_data.get(scrim_id)
            if not scrim_data: return

            embed = self.create_scrim_embed(scrim_data)
            # Re-create the view to update button states if necessary (or pass scrim_id and let it handle it)
            view = ScrimView(self.bot, scrim_id)
            await message.edit(embed=embed, view=view)
        except discord.NotFound:
            self.logger.warning(f"Failed to update scrim message for {scrim_id}: Message not found.")
        except Exception as e:
            self.logger.error(f"Error updating scrim message {scrim_id}: {e}", exc_info=True)

    @tasks.loop(minutes=1)
    async def scrim_notifications(self):
        """내전 시작 시간 전에 알림 전송"""
        try:
            eastern = pytz.timezone('America/New_York')
            now = datetime.now(eastern)

            for scrim_id, scrim_data in list(self.scrims_data.items()):
                if scrim_data['status'] != '활성':
                    continue

                start_time = scrim_data['start_time']
                # Convert UTC stored time to Eastern for comparison
                if start_time.tzinfo == pytz.utc:
                    start_time = start_time.astimezone(eastern)
                elif start_time.tzinfo is None:
                    # If somehow no timezone, assume it's UTC
                    start_time = pytz.utc.localize(start_time).astimezone(eastern)

                time_until_start = start_time - now
                is_full = len(scrim_data['participants']) >= scrim_data['max_players']
                notifications_sent = scrim_data.get('notifications_sent', {'10min': False, '2min': False})

                # 10분 알림 (15분에서 5분 사이)
                if (timedelta(minutes=5) <= time_until_start <= timedelta(minutes=15) and
                        not notifications_sent.get('10min') and is_full):
                    await self.send_scrim_notification(scrim_data, "10분")
                    notifications_sent['10min'] = True
                    scrim_data['notifications_sent'] = notifications_sent
                    await self.save_scrims_data()

                # 2분 알림 (5분에서 0분 사이)
                elif (timedelta(seconds=1) <= time_until_start <= timedelta(minutes=5) and
                      not notifications_sent.get('2min') and is_full):
                    await self.send_scrim_notification(scrim_data, "2분")
                    notifications_sent['2min'] = True
                    scrim_data['notifications_sent'] = notifications_sent
                    await self.save_scrims_data()

                # 시작 시간이 지난 경우 완료로 표시
                elif time_until_start.total_seconds() <= 0:
                    scrim_data['status'] = '완료됨'
                    await self.save_scrims_data()

                    if scrim_data.get('message_id'):
                        guild = self.bot.get_guild(scrim_data['guild_id'])
                        if guild:
                            channel = guild.get_channel(scrim_data['channel_id'])
                            if channel:
                                try:
                                    message = await channel.fetch_message(scrim_data['message_id'])
                                    await self.update_scrim_message(message, scrim_id)
                                except discord.NotFound:
                                    pass
        except Exception as e:
            self.logger.error(f"Error in scrim notification task: {e}", exc_info=True)

    async def send_scrim_notification(self, scrim_data: Dict, time_text: str):
        try:
            guild = self.bot.get_guild(scrim_data['guild_id'])
            if not guild: return

            mentions = [f"<@{user_id}>" for user_id in scrim_data['participants']]
            if not mentions: return

            embed = discord.Embed(
                title=f"⏰ 내전이 {time_text} 후 시작됩니다",
                description=f"**{scrim_data['game']}** 내전이 곧 시작됩니다! 준비해주세요.",
                color=discord.Color.orange()
            )
            embed.add_field(name="게임 모드", value=scrim_data['gamemode'], inline=True)
            embed.add_field(name="시작 시간", value=f"<t:{int(scrim_data['start_time'].timestamp())}:T>", inline=True)

            channel = guild.get_channel(scrim_data['channel_id'])
            if channel:
                await channel.send(content=" ".join(mentions), embed=embed)
            self.logger.info(f"Sent {time_text} notification for scrim {scrim_data['id']}.")
        except Exception as e:
            self.logger.error(f"Error sending scrim notification: {e}", exc_info=True)

    @tasks.loop(hours=6)
    async def cleanup_old_scrims(self):
        """오래된 완료/취소된 내전 정리"""
        try:
            now = datetime.now(pytz.utc)
            cutoff_time = now - timedelta(days=7)

            scrims_to_remove = []
            for scrim_id, scrim_data in self.scrims_data.items():
                start_time = scrim_data['start_time'].astimezone(pytz.utc)
                if scrim_data['status'] in ['완료됨', '취소됨'] and start_time < cutoff_time:
                    scrims_to_remove.append(scrim_id)

            if scrims_to_remove:
                for scrim_id in scrims_to_remove:
                    del self.scrims_data[scrim_id]
                await self.save_scrims_data()
                self.logger.info(f"Cleaned up {len(scrims_to_remove)} old scrim(s).")
        except Exception as e:
            self.logger.error(f"Error in cleanup task: {e}", exc_info=True)

    async def migrate_timezone_data(self):
        """One-time migration to fix timezone data in existing scrims."""
        try:
            eastern = pytz.timezone('America/New_York')
            migration_needed = False

            for scrim_id, scrim_data in self.scrims_data.items():
                start_time = scrim_data['start_time']

                # Check if this looks like it needs migration
                if isinstance(start_time, str):
                    # If it's still a string, parse and assume it's Eastern time
                    dt = datetime.fromisoformat(start_time)
                    if dt.tzinfo is None:
                        # Assume this was stored as Eastern time, convert to UTC
                        eastern_time = eastern.localize(dt)
                        scrim_data['start_time'] = eastern_time.astimezone(pytz.utc)
                        migration_needed = True
                elif start_time.tzinfo is None:
                    # Naive datetime, assume Eastern and convert to UTC
                    eastern_time = eastern.localize(start_time)
                    scrim_data['start_time'] = eastern_time.astimezone(pytz.utc)
                    migration_needed = True
                elif start_time.tzinfo != pytz.utc:
                    # Already has timezone but not UTC, convert to UTC
                    scrim_data['start_time'] = start_time.astimezone(pytz.utc)
                    migration_needed = True

                # Do the same for created_at
                created_at = scrim_data['created_at']
                if isinstance(created_at, str):
                    dt = datetime.fromisoformat(created_at)
                    if dt.tzinfo is None:
                        eastern_time = eastern.localize(dt)
                        scrim_data['created_at'] = eastern_time.astimezone(pytz.utc)
                        migration_needed = True
                elif created_at.tzinfo is None:
                    eastern_time = eastern.localize(created_at)
                    scrim_data['created_at'] = eastern_time.astimezone(pytz.utc)
                    migration_needed = True
                elif created_at.tzinfo != pytz.utc:
                    scrim_data['created_at'] = created_at.astimezone(pytz.utc)
                    migration_needed = True

            if migration_needed:
                await self.save_scrims_data()
                self.logger.info("Completed timezone data migration.")
            else:
                self.logger.info("No timezone migration needed.")

        except Exception as e:
            self.logger.error(f"Error during timezone migration: {e}", exc_info=True)

    @app_commands.command(name="맵선택", description="활성 맵 풀에서 무작위 맵을 선택합니다.")
    @app_commands.describe(count="선택할 맵의 수 (기본값: 1)")
    async def random_map(self, interaction: discord.Interaction, count: app_commands.Range[int, 1, 10] = 1):
        if not config.is_feature_enabled(interaction.guild.id, 'scrim_system'):
            await interaction.response.send_message("❌ 이 서버에서 내전 시스템이 비활성화되어 있습니다.", ephemeral=True)
            return

        map_pool = self.get_map_pool(interaction.guild.id)
        if not map_pool or len(map_pool) < count:
            await interaction.response.send_message(f"❌ 맵 풀에 맵이 부족합니다. (필요: {count}, 보유: {len(map_pool)})",
                                                    ephemeral=True)
            return

        selected_maps = random.sample(map_pool, count)
        embed = discord.Embed(title="🎯 무작위 맵 선택", color=discord.Color.green())
        map_list = "\n".join([f"**{map_name}**" for map_name in selected_maps])
        embed.description = f"**선택된 맵:**\n{map_list}"
        embed.set_footer(text=f"{interaction.user.display_name}의 요청")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="맵풀설정", description="서버의 맵 풀을 설정합니다. (관리자 전용)")
    @app_commands.default_permissions(administrator=True)
    async def set_map_pool(self, interaction: discord.Interaction):
        current_maps = self.get_map_pool(interaction.guild.id)
        await interaction.response.send_modal(MapPoolModal(self.bot, interaction.guild.id, current_maps))

    @app_commands.command(name="맵풀확인", description="현재 서버의 맵 풀을 표시합니다.")
    async def show_map_pool(self, interaction: discord.Interaction):
        map_pool = self.get_map_pool(interaction.guild.id)
        embed = discord.Embed(title="🗺️ 현재 맵 풀", color=discord.Color.blue())
        if map_pool:
            map_list = "\n".join([f"• {map_name}" for map_name in map_pool])
            embed.description = f"**총 {len(map_pool)} 맵:**\n{map_list}"
        else:
            embed.description = "설정된 맵이 없습니다."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="내전기록", description="이 서버의 활성 내전을 확인합니다.")
    async def list_scrims(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id
        active_scrims = [sd for sd in self.scrims_data.values() if sd['guild_id'] == guild_id and sd['status'] == '활성']

        if not active_scrims:
            await interaction.followup.send("현재 활성 내전이 없습니다.", ephemeral=True)
            return

        embed = discord.Embed(title="🎮 활성 내전 목록", color=discord.Color.blue())
        sorted_scrims = sorted(active_scrims, key=lambda x: x['start_time'])

        for scrim_data in sorted_scrims:
            start_timestamp = int(scrim_data['start_time'].timestamp())
            embed.add_field(
                name=f"{scrim_data['game']} ({scrim_data['gamemode']})",
                value=f"시작: <t:{start_timestamp}:R>\n"
                      f"플레이어: {len(scrim_data['participants'])}/{scrim_data['max_players']}\n"
                      f"ID: `{scrim_data['id']}`",
                inline=True
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="내전설정", description="내전 시스템 설정을 구성합니다. (관리자 전용)")
    @app_commands.describe(feature_enabled="내전 시스템 활성화/비활성화", scrim_channel="내전 생성 패널이 표시될 채널")
    @app_commands.default_permissions(administrator=True)
    async def configure_scrim(self, interaction: discord.Interaction, feature_enabled: Optional[bool] = None,
                              scrim_channel: Optional[discord.TextChannel] = None):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id
        updated = False
        if feature_enabled is not None:
            config.set_feature_enabled(guild_id, 'scrim_system', feature_enabled)
            updated = True
        if scrim_channel is not None:
            config.set_channel_id(guild_id, 'scrim_channel', scrim_channel.id, scrim_channel.name)
            if feature_enabled is not False:  # Only setup panel if system is not being disabled
                await self.setup_scrim_panel(scrim_channel)
            updated = True

        if updated:
            await interaction.followup.send("✅ 내전 시스템 설정이 성공적으로 업데이트되었습니다.")
        else:
            await interaction.followup.send("ℹ️ 설정에 변경 사항이 없습니다.")

    @app_commands.command(name="내전강제취소", description="내전을 강제로 취소합니다. (스태프 전용)")
    @app_commands.describe(scrim_id="취소할 내전의 ID")
    async def force_cancel_scrim(self, interaction: discord.Interaction, scrim_id: str):
        if not self.has_staff_permissions(interaction.user):
            await interaction.response.send_message("❌ 이 명령어를 사용할 권한이 없습니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        scrim_data = self.scrims_data.get(scrim_id)
        if not scrim_data or scrim_data['guild_id'] != interaction.guild.id:
            await interaction.followup.send("❌ 이 서버에서 해당 ID의 내전을 찾을 수 없습니다.", ephemeral=True)
            return

        success = await self.cancel_scrim(scrim_id, interaction.user.id)
        if success:
            await interaction.followup.send(f"✅ 내전 `{scrim_id}`이(가) 취소되었습니다.", ephemeral=True)
            if scrim_data.get('message_id'):
                try:
                    channel = interaction.guild.get_channel(scrim_data['channel_id'])
                    message = await channel.fetch_message(scrim_data['message_id'])
                    await self.update_scrim_message(message, scrim_id)
                except Exception:
                    pass  # Message might be deleted, it's ok
        else:
            await interaction.followup.send("❌ 내전 취소 중 오류가 발생했습니다.", ephemeral=True)

    @app_commands.command(name="내전패널재설정", description="내전 패널 메시지를 새로 고칩니다. (관리자 전용)")
    @app_commands.default_permissions(administrator=True)
    async def refresh_scrim_panel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        scrim_channel_id = config.get_channel_id(interaction.guild.id, 'scrim_channel')
        if not scrim_channel_id:
            await interaction.followup.send("❌ 내전 채널이 설정되지 않았습니다.", ephemeral=True)
            return

        channel = interaction.guild.get_channel(scrim_channel_id)
        if not channel:
            await interaction.followup.send("❌ 설정된 내전 채널을 찾을 수 없습니다.", ephemeral=True)
            return

        # Delete old panels
        async for message in channel.history(limit=50):
            if message.author == self.bot.user and message.embeds and "내전 생성 패널" in message.embeds[0].title:
                await message.delete()

        await self.setup_scrim_panel(channel)
        await interaction.followup.send("✅ 내전 패널이 성공적으로 새로 고쳐졌습니다.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(ScrimCog(bot))