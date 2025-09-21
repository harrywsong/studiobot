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

            if hasattr(self, 'message') and self.message:
                embed = discord.Embed(
                    title="⏱️ 시간 초과",
                    description="이 메뉴가 만료되었습니다. 새로운 내전 생성을 시작해주세요.",
                    color=discord.Color.red()
                )
                await self.message.edit(embed=embed, view=self)
        except Exception as e:
            print(f"ERROR in PlayerCountSelectView on_timeout: {str(e)}\nFull traceback: {traceback.format_exc()}")
            self.logger.error(f"Timeout error in PlayerCountSelectView: {traceback.format_exc()}")

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
            gamemode_view.message = interaction.message  # ADD THIS LINE

        except Exception as e:
            print(f"ERROR in game_selected: {str(e)}\nFull traceback: {traceback.format_exc()}")
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

            # Try to edit the message to show it's expired
            if hasattr(self, 'message') and self.message:
                embed = discord.Embed(
                    title="⏱️ 시간 초과",
                    description="이 메뉴가 만료되었습니다. 새로운 내전 생성을 시작해주세요.",
                    color=discord.Color.red()
                )
                await self.message.edit(embed=embed, view=self)
        except Exception as e:
            print(f"ERROR in GameSelectView on_timeout: {str(e)}\nFull traceback: {traceback.format_exc()}")
            self.logger.error(f"Timeout error in GameSelectView: {traceback.format_exc()}")

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
            tier_view.message = interaction.message  # ADD THIS LINE

        except Exception as e:
            print(f"ERROR in gamemode_selected: {str(e)}\nFull traceback: {traceback.format_exc()}")
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
            game_view.message = interaction.message  # ADD THIS LINE
        except Exception as e:
            print(f"ERROR in back_to_game_selection: {str(e)}\nFull traceback: {traceback.format_exc()}")
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

        # 모든 게임에 대한 일반화된 티어 옵션
        tier_options = [
            discord.SelectOption(label="모든 티어", value="All tiers", emoji="🌐"),
            discord.SelectOption(label="아이언 - 브론즈", value="Iron-Bronze", emoji="<:valorantbronze:1367050339987095563> "),
            discord.SelectOption(label="실버 - 골드", value="Silver-Gold", emoji="<:valorantgold:1367050331242106951> "),
            discord.SelectOption(label="골드 - 플래티넘", value="Gold-Platinum", emoji="<:valorantplatinum:1367055859435175986> "),
            discord.SelectOption(label="플래티넘 - 다이아몬드", value="Plat-Diamond", emoji="<:valorantdiamond:1367055861351972905> "),
            discord.SelectOption(label="초월자", value="Ascendant", emoji="<:valorantascendant:1367050328976920606> "),
            discord.SelectOption(label="불멸+", value="Immortal+", emoji="<:valorantimmortal:1367050346874011668> "),
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

        # 뒤로 가기 버튼
        back_button = discord.ui.Button(
            label="뒤로",
            style=discord.ButtonStyle.secondary,
            emoji="⬅️"
        )
        back_button.callback = self.back_to_gamemode_selection
        self.add_item(back_button)

    async def on_timeout(self):
        """Handle view timeout"""
        try:
            for item in self.children:
                item.disabled = True

            if hasattr(self, 'message') and self.message:
                embed = discord.Embed(
                    title="⏱️ 시간 초과",
                    description="이 메뉴가 만료되었습니다. 새로운 내전 생성을 시작해주세요.",
                    color=discord.Color.red()
                )
                await self.message.edit(embed=embed, view=self)
        except Exception as e:
            print(f"ERROR in GameModeSelectView on_timeout: {str(e)}\nFull traceback: {traceback.format_exc()}")
            self.logger.error(f"Timeout error in GameModeSelectView: {traceback.format_exc()}")

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
            time_view.message = interaction.message  # ADD THIS LINE

        except Exception as e:
            print(f"ERROR in tier_selected: {str(e)}\nFull traceback: {traceback.format_exc()}")
            self.logger.error(f"Tier selection error: {traceback.format_exc()}")
            try:
                await interaction.followup.send(f"⚠ 오류가 발생했습니다: {str(e)}", ephemeral=True)
            except:
                pass

    async def back_to_gamemode_selection(self, interaction: discord.Interaction):
        """게임 모드 선택으로 돌아가기"""
        try:
            await interaction.response.defer()

            # Re-create the previous view (GameModeSelectView)
            gamemode_view = GameModeSelectView(
                self.bot, self.guild_id, self.game, self.role_id
            )

            # Re-create the embed for that view
            embed = discord.Embed(
                title="🎮 게임 모드 선택",
                description=f"**선택된 게임:** {self.game}\n\n이제 게임 모드를 선택하세요:",
                color=discord.Color.blue()
            )

            # Edit the message to go back
            await interaction.edit_original_response(embed=embed, view=gamemode_view)
            gamemode_view.message = interaction.message  # ADD THIS LINE

        except Exception as e:
            print(f"ERROR in back_to_gamemode_selection: {str(e)}\nFull traceback: {traceback.format_exc()}")
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

        # 시간 옵션 (customize as needed)
        time_options = [
            discord.SelectOption(label="30분 후", value="30min", emoji="⏱️"),
            discord.SelectOption(label="1시간 후", value="1hour", emoji="🕐"),
            discord.SelectOption(label="2시간 후", value="2hour", emoji="🕑"),
            discord.SelectOption(label="오늘 저녁 8시", value="tonight", emoji="🌙"),
            discord.SelectOption(label="사용자 지정", value="custom", emoji="⚙️")
        ]

        self.time_select = discord.ui.Select(
            placeholder="시작 시간 선택...",
            options=time_options,
            custom_id="time_select"
        )
        self.time_select.callback = self.time_selected
        self.add_item(self.time_select)

        # 뒤로 가기 버튼
        back_button = discord.ui.Button(
            label="뒤로",
            style=discord.ButtonStyle.secondary,
            emoji="⬅️"
        )
        back_button.callback = self.back_to_tier_selection
        self.add_item(back_button)

    async def on_timeout(self):
        """Handle view timeout"""
        try:
            for item in self.children:
                item.disabled = True

            if hasattr(self, 'message') and self.message:
                embed = discord.Embed(
                    title="⏱️ 시간 초과",
                    description="이 메뉴가 만료되었습니다. 새로운 내전 생성을 시작해주세요.",
                    color=discord.Color.red()
                )
                await self.message.edit(embed=embed, view=self)
        except Exception as e:
            print(f"ERROR in TimeSelectView on_timeout: {str(e)}\nFull traceback: {traceback.format_exc()}")
            self.logger.error(f"Timeout error in TimeSelectView: {traceback.format_exc()}")

    async def time_selected(self, interaction: discord.Interaction):
        """시간 선택 처리"""
        try:
            selection = self.time_select.values[0]

            if selection == "custom":
                # For custom time, show modal immediately
                modal = CustomTimeModal(
                    self.bot, self.guild_id, self.game, self.gamemode,
                    self.tier, self.role_id, original_view=self  # Pass self for message reference
                )
                await interaction.response.send_modal(modal)
                return

            # For non-custom selections, defer first
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
                if tonight <= now:
                    tonight += timedelta(days=1)
                self.selected_time = tonight

            # Continue to player count view
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
            player_view.message = interaction.message

        except Exception as e:
            print(f"ERROR in time_selected: {str(e)}\nFull traceback: {traceback.format_exc()}")
            self.logger.error(f"Time selection error: {traceback.format_exc()}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"⚠ 오류가 발생했습니다: {str(e)}", ephemeral=True)
                else:
                    await interaction.followup.send(f"⚠ 오류가 발생했습니다: {str(e)}", ephemeral=True)
            except:
                pass

    async def continue_to_player_count(self, interaction: discord.Interaction):
        """플레이어 수 선택으로 이동"""
        player_view = PlayerCountSelectView(
            self.bot, self.guild_id, self.game, self.gamemode,
            self.tier, self.selected_time, self.role_id
        )

        embed = discord.Embed(
            title="👥 플레이어 수 선택",
            description=f"**게임:** {self.game}\n**모드:** {self.gamemode}\n**티어:** {self.tier}\n**시간:** {self.selected_time.strftime('%Y-%m-%d %H:%M EST')}\n\n최대 플레이어 수는 몇 명인가요?",
            color=discord.Color.purple()
        )

        await interaction.edit_original_response(embed=embed, view=player_view)
        player_view.message = interaction.message  # ADD THIS LINE

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
            tier_view.message = interaction.message
        except Exception as e:
            print(f"ERROR in back_to_tier_selection: {str(e)}\nFull traceback: {traceback.format_exc()}")
            self.logger.error(f"Back to tier selection error: {traceback.format_exc()}")
            try:
                await interaction.followup.send(f"⚠ 오류가 발생했습니다: {str(e)}", ephemeral=True)
            except:
                pass

class CustomTimeModal(discord.ui.Modal, title="사용자 지정 시간 입력"):
    def __init__(self, bot, guild_id: int, game: str, gamemode: str, tier: str, role_id: int, original_view=None):
        super().__init__()
        self.bot = bot
        self.guild_id = guild_id
        self.game = game
        self.gamemode = gamemode
        self.tier = tier
        self.role_id = role_id
        self.original_view = original_view  # Reference for editing original message

        self.time_input = discord.ui.TextInput(
            label="시간 입력 (예: 2025-09-21 00:00 EST 또는 30분 후)",
            style=discord.TextStyle.short,
            placeholder="YYYY-MM-DD HH:MM EST 또는 상대 시간",
            required=True
        )
        self.add_item(self.time_input)

    async def on_submit(self, interaction: discord.Interaction):
        eastern = pytz.timezone('America/New_York')
        try:
            parsed_time = await self.parse_time_input(self.time_input.value, eastern)
            if not parsed_time:
                await interaction.response.send_message("⚠ 잘못된 시간 형식입니다. 다시 시도해주세요.", ephemeral=True)
                return

            if parsed_time <= datetime.now(eastern):
                await interaction.response.send_message("⚠ 시작 시간은 미래여야 합니다.", ephemeral=True)
                return

            if self.original_view and hasattr(self.original_view, 'message') and self.original_view.message:
                await interaction.response.defer()

                player_view = PlayerCountSelectView(
                    self.bot, self.guild_id, self.game, self.gamemode,
                    self.tier, parsed_time, self.role_id
                )

                embed = discord.Embed(
                    title="👥 최대 플레이어 수 선택",
                    description=f"**게임:** {self.game}\n**모드:** {self.gamemode}\n**티어:** {self.tier}\n**시작 시간:** {parsed_time.strftime('%Y-%m-%d %H:%M EST')}\n\n최대 플레이어 수를 선택하세요:",
                    color=discord.Color.purple()
                )

                await self.original_view.message.edit(embed=embed, view=player_view)
                player_view.message = self.original_view.message

                await interaction.followup.send(f"✅ 시간이 {parsed_time.strftime('%Y-%m-%d %H:%M EST')}로 설정되었습니다. 계속 진행 중...", ephemeral=True)
            else:
                await interaction.response.send_message(
                    f"✅ 시간이 {parsed_time.strftime('%Y-%m-%d %H:%M EST')}로 설정되었습니다. 다시 내전 생성을 시작해주세요.",
                    ephemeral=True
                )

        except Exception as e:
            print(f"ERROR in CustomTimeModal on_submit: {str(e)}\nFull traceback: {traceback.format_exc()}")
            self.logger.error(f"Custom time submit error: {traceback.format_exc()}")
            await interaction.response.send_message(f"⚠ 시간 처리 중 오류가 발생했습니다: {str(e)}", ephemeral=True)

    async def parse_time_input(self, input_str: str, tz) -> Optional[datetime]:
        # Implement parsing logic here (example: handle absolute/relative times)
        # This is a placeholder - customize based on your needs
        try:
            if '후' in input_str:  # Relative time, e.g., "30분 후"
                minutes = int(input_str.split()[0].replace('분', ''))
                return datetime.now(tz) + timedelta(minutes=minutes)
            else:  # Absolute time, e.g., "2025-09-21 00:00 EST"
                return tz.localize(datetime.strptime(input_str, '%Y-%m-%d %H:%M EST'))
        except:
            return None


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

        # 플레이어 수 옵션 (customize as needed for your games)
        player_options = [
            discord.SelectOption(label="10명", value="10", emoji="👥"),
            discord.SelectOption(label="20명", value="20", emoji="👥👥"),
            discord.SelectOption(label="30명", value="30", emoji="👥👥👥"),
            discord.SelectOption(label="사용자 지정", value="custom", emoji="⚙️")
        ]

        self.player_select = discord.ui.Select(
            placeholder="최대 플레이어 수 선택...",
            options=player_options,
            custom_id="player_select"
        )
        self.player_select.callback = self.player_selected
        self.add_item(self.player_select)

        # 뒤로 가기 버튼
        back_button = discord.ui.Button(
            label="뒤로",
            style=discord.ButtonStyle.secondary,
            emoji="⬅️"
        )
        back_button.callback = self.back_to_time_selection
        self.add_item(back_button)

    async def on_timeout(self):
        """Handle view timeout"""
        try:
            for item in self.children:
                item.disabled = True

            if hasattr(self, 'message') and self.message:
                embed = discord.Embed(
                    title="⏱️ 시간 초과",
                    description="이 메뉴가 만료되었습니다. 새로운 내전 생성을 시작해주세요.",
                    color=discord.Color.red()
                )
                await self.message.edit(embed=embed, view=self)
        except Exception as e:
            print(f"ERROR in PlayerCountSelectView on_timeout: {str(e)}\nFull traceback: {traceback.format_exc()}")
            self.logger.error(f"Timeout error in PlayerCountSelectView: {traceback.format_exc()}")

    async def player_selected(self, interaction: discord.Interaction):
        """플레이어 수 선택 처리"""
        try:
            selection = self.player_select.values[0]

            if selection == "custom":
                # Handle custom player count with a modal (similar to time)
                modal = CustomPlayerCountModal(
                    self.bot, self.guild_id, self.game, self.gamemode,
                    self.tier, self.start_time, self.role_id, original_view=self
                )
                await interaction.response.send_modal(modal)
                return

            await interaction.response.defer()

            self.selected_max_players = int(selection)

            # Proceed to create the scrim (implement this method in ScrimCog if missing)
            await self.create_scrim(interaction, self.selected_max_players)  # This line calls your scrim creation logic

        except Exception as e:
            print(f"ERROR in player_selected: {str(e)}\nFull traceback: {traceback.format_exc()}")
            self.logger.error(f"Player selection error: {traceback.format_exc()}")
            try:
                await interaction.followup.send(f"⚠ 오류가 발생했습니다: {str(e)}", ephemeral=True)
            except:
                pass

    async def create_scrim(self, interaction: discord.Interaction, max_players: int):
        """Create scrim with immediate deferral"""
        try:
            # Defer immediately if not already done
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)

            scrim_cog = self.bot.get_cog('ScrimCog')
            if scrim_cog:
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
                    await interaction.followup.send("✅ 내전이 성공적으로 생성되었습니다!", ephemeral=True)

                    # Do heavy operations in background
                    asyncio.create_task(self.post_scrim_and_notify_safe(scrim_cog, scrim_id))
                else:
                    await interaction.followup.send("❌ 내전 생성 중 오류가 발생했습니다.", ephemeral=True)
            else:
                await interaction.followup.send("❌ 내전 시스템을 찾을 수 없습니다.", ephemeral=True)

        except Exception as e:
            logger = get_logger("내부 매치")
            logger.error(f"Create scrim error: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ 오류가 발생했습니다.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ 오류가 발생했습니다.", ephemeral=True)
            except:
                pass

    async def post_scrim_and_notify_safe(self, scrim_cog, scrim_id):
        """Safe background task that won't affect interaction timing"""
        try:
            await asyncio.sleep(0.1)  # Small delay to ensure interaction completes
            await self.post_scrim_and_notify(scrim_cog, scrim_id)
        except Exception as e:
            logger = get_logger("내부 매치")
            logger.error(f"Background notification error: {e}")

    async def post_scrim_and_notify(self, scrim_cog, scrim_id):
        """Background task to post scrim message and send role notifications"""
        try:
            # Get scrim data
            scrim_data = scrim_cog.scrims_data.get(scrim_id)
            if not scrim_data:
                return

            # Post scrim message to channel
            guild = self.bot.get_guild(scrim_data['guild_id'])
            if guild:
                channel = guild.get_channel(scrim_data['channel_id'])
                if channel:
                    await scrim_cog.post_scrim_message(channel, scrim_id)

            # Send role notification if role_id is set
            if self.role_id and guild:
                role = guild.get_role(self.role_id)
                if role and channel:
                    try:
                        mention_msg = await channel.send(f"{role.mention} 새로운 내전이 생성되었습니다!")
                        # Delete the mention after 5 seconds to avoid spam
                        await asyncio.sleep(5)
                        await mention_msg.delete()
                    except Exception:
                        pass  # If deletion fails, continue

        except Exception as e:
            logger = get_logger("내부 매치")
            logger.error(f"Background task error: {e}")

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
            time_view.message = interaction.message
        except Exception as e:
            print(f"ERROR in back_to_time_selection: {str(e)}\nFull traceback: {traceback.format_exc()}")
            self.logger.error(f"Back to time selection error: {traceback.format_exc()}")
            try:
                await interaction.followup.send(f"⚠ 오류가 발생했습니다: {str(e)}", ephemeral=True)
            except:
                pass

class CustomPlayerCountModal(discord.ui.Modal, title="사용자 지정 플레이어 수 입력"):
    def __init__(self, bot, guild_id: int, game: str, gamemode: str, tier: str, start_time: datetime, role_id: int, original_view=None):
        super().__init__()
        self.bot = bot
        self.guild_id = guild_id
        self.game = game
        self.gamemode = gamemode
        self.tier = tier
        self.start_time = start_time
        self.role_id = role_id
        self.original_view = original_view

        self.player_input = discord.ui.TextInput(
            label="최대 플레이어 수 입력 (예: 15)",
            style=discord.TextStyle.short,
            placeholder="숫자만 입력",
            required=True
        )
        self.add_item(self.player_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            max_players = int(self.player_input.value)
            if max_players <= 0:
                await interaction.response.send_message("⚠ 플레이어 수는 1 이상이어야 합니다.", ephemeral=True)
                return

            if self.original_view and hasattr(self.original_view, 'message') and self.original_view.message:
                await interaction.response.defer()

                # Proceed to create scrim directly after custom input
                await self.original_view.create_scrim(interaction, max_players)  # Call create_scrim

                await interaction.followup.send(f"✅ 플레이어 수가 {max_players}로 설정되었습니다. 내전 생성 중...", ephemeral=True)
            else:
                await interaction.response.send_message(
                    f"✅ 플레이어 수가 {max_players}로 설정되었습니다. 다시 내전 생성을 시작해주세요.",
                    ephemeral=True
                )

        except ValueError:
            await interaction.response.send_message("⚠ 유효한 숫자를 입력해주세요.", ephemeral=True)
        except Exception as e:
            print(f"ERROR in CustomPlayerCountModal on_submit: {str(e)}\nFull traceback: {traceback.format_exc()}")
            self.logger.error(f"Custom player submit error: {traceback.format_exc()}")
            await interaction.response.send_message(f"⚠ 플레이어 수 처리 중 오류가 발생했습니다: {str(e)}", ephemeral=True)

class CustomPlayerCountModal(discord.ui.Modal):
    """사용자 지정 플레이어 수 입력을 위한 모달"""

    def __init__(self, bot, guild_id: int, game: str, gamemode: str, tier: str, start_time: datetime, role_id: int):
        super().__init__(title="사용자 지정 플레이어 수", timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.game = game
        self.gamemode = gamemode
        self.tier = tier
        self.start_time = start_time
        self.role_id = role_id
        self.logger = get_logger("내부 매치")

        self.player_input = discord.ui.TextInput(
            label="최대 플레이어 수",
            placeholder="2-50 사이의 숫자를 입력하세요",
            required=True,
            max_length=2
        )
        self.add_item(self.player_input)

    async def on_submit(self, interaction: discord.Interaction):
        """사용자 지정 플레이어 수 제출 처리"""
        try:
            max_players = int(self.player_input.value)
            if max_players < 2 or max_players > 50:
                await interaction.response.send_message(
                    "⚠ 플레이어 수는 2-50 사이여야 합니다.", ephemeral=True
                )
                return

            await interaction.response.send_message(
                f"✅ 플레이어 수가 {max_players}명으로 설정되었습니다. 다시 내전 생성을 시작해주세요.",
                ephemeral=True
            )

        except ValueError:
            await interaction.response.send_message(
                "⚠ 유효한 숫자를 입력하세요.", ephemeral=True
            )


class MapPoolModal(discord.ui.Modal):
    """맵 풀 관리를 위한 모달"""

    def __init__(self, bot, guild_id: int, current_maps: List[str]):
        super().__init__(title="맵 풀 설정", timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.logger = get_logger("내부 매치")

        # 현재 맵 문자열 생성, 너무 길지 않도록 제한
        current_maps_str = ", ".join(current_maps)
        if len(current_maps_str) > 490:  # 안전을 위해 여유 공간 확보
            current_maps_str = current_maps_str[:490] + "..."

        # 맵 풀 입력
        self.map_input = discord.ui.TextInput(
            label="맵 목록 (쉼표로 구분)",
            placeholder="예: 바인드, 헤이븐, 스플릿, 어센트...",
            default=current_maps_str,
            required=True,
            max_length=500,
            style=discord.TextStyle.paragraph
        )

        self.add_item(self.map_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # 입력에서 맵 파싱
            map_list = [map_name.strip() for map_name in self.map_input.value.split(',') if map_name.strip()]

            if len(map_list) < 2:
                await interaction.response.send_message("❌ 최소 2개의 맵이 필요합니다.", ephemeral=True)
                return

            # 내전 Cog 가져오고 맵 풀 업데이트
            scrim_cog = self.bot.get_cog('ScrimCog')
            if scrim_cog:
                success = await scrim_cog.update_map_pool(self.guild_id, map_list)
                if success:
                    # 응답 메시지 생성, 너무 길 경우 잘라냄
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
            self.logger.error(f"길드 {self.guild_id}의 맵 풀 모달에서 오류 발생: {e}",
                              extra={'guild_id': self.guild_id})
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ 오류가 발생했습니다. 다시 시도해주세요.", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        self.logger.error(f"길드 {self.guild_id}의 모달 오류: {error}", extra={'guild_id': self.guild_id})
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ 오류가 발생했습니다. 다시 시도해주세요.", ephemeral=True)


class ScrimView(discord.ui.View):
    """버튼 스타일이 개선된 내전 뷰"""

    def __init__(self, bot, scrim_data: Dict):
        super().__init__(timeout=None)
        self.bot = bot
        self.scrim_data = scrim_data
        self.scrim_id = scrim_data['id']
        self.guild_id = scrim_data['guild_id']
        self.logger = get_logger("내부 매치")

        # 버튼 상태 업데이트
        self.update_button_states()

    def update_button_states(self):
        """현재 내전 상태에 따라 버튼 상태 업데이트"""
        eastern = pytz.timezone('America/New_York')
        now = datetime.now(eastern)
        start_time = self.scrim_data['start_time']

        if start_time.tzinfo is None:
            start_time = eastern.localize(start_time)

        time_until_start = start_time - now
        buttons_locked = time_until_start <= timedelta(minutes=30)

        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.custom_id in [
                'join_scrim', 'leave_scrim', 'join_queue', 'leave_queue'
            ]:
                item.disabled = buttons_locked

    @discord.ui.button(
        label="참가",
        style=discord.ButtonStyle.success,
        custom_id="join_scrim",
        emoji="✅"
    )
    async def join_scrim(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Join scrim with proper error handling"""
        try:
            await interaction.response.defer(ephemeral=True)  # ADD THIS

            scrim_cog = self.bot.get_cog('ScrimCog')
            if not scrim_cog:
                await interaction.followup.send("❌ 내전 시스템을 찾을 수 없습니다.", ephemeral=True)
                return

            success, message = await scrim_cog.join_scrim(interaction.user.id, self.scrim_id)
            await interaction.followup.send(message, ephemeral=True)

            if success:
                # Don't wait for message update
                asyncio.create_task(scrim_cog.update_scrim_message(interaction.message, self.scrim_id))

        except Exception as e:
            self.logger.error(f"Join scrim error: {e}")
            try:
                await interaction.followup.send("❌ 오류가 발생했습니다.", ephemeral=True)
            except:
                pass

    @discord.ui.button(
        label="나가기",
        style=discord.ButtonStyle.danger,
        custom_id="leave_scrim",
        emoji="❌"
    )
    async def leave_scrim(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Leave scrim with proper error handling"""
        try:
            await interaction.response.defer(ephemeral=True)  # DEFER FIRST

            scrim_cog = self.bot.get_cog('ScrimCog')
            if not scrim_cog:
                await interaction.followup.send("❌ 내전 시스템을 찾을 수 없습니다.", ephemeral=True)
                return

            success, message = await scrim_cog.leave_scrim(interaction.user.id, self.scrim_id)
            await interaction.followup.send(message, ephemeral=True)  # CHANGED from response.send

            if success:
                # Don't wait for message update - run in background
                asyncio.create_task(scrim_cog.update_scrim_message(interaction.message, self.scrim_id))

        except Exception as e:
            self.logger.error(f"Leave scrim error: {e}")
            try:
                await interaction.followup.send("❌ 오류가 발생했습니다.", ephemeral=True)
            except:
                pass

    @discord.ui.button(
        label="대기열 참가",
        style=discord.ButtonStyle.secondary,
        custom_id="join_queue",
        emoji="⏳"
    )
    async def join_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Join queue with proper error handling"""
        try:
            await interaction.response.defer(ephemeral=True)  # DEFER FIRST

            scrim_cog = self.bot.get_cog('ScrimCog')
            if not scrim_cog:
                await interaction.followup.send("❌ 내전 시스템을 찾을 수 없습니다.", ephemeral=True)
                return

            success, message = await scrim_cog.join_queue(interaction.user.id, self.scrim_id)
            await interaction.followup.send(message, ephemeral=True)  # CHANGED from response.send

            if success:
                # Don't wait for message update - run in background
                asyncio.create_task(scrim_cog.update_scrim_message(interaction.message, self.scrim_id))

        except Exception as e:
            self.logger.error(f"Join queue error: {e}")
            try:
                await interaction.followup.send("❌ 오류가 발생했습니다.", ephemeral=True)
            except:
                pass

    @discord.ui.button(
        label="대기열 나가기",
        style=discord.ButtonStyle.secondary,
        custom_id="leave_queue",
        emoji="🚪"
    )
    async def leave_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Leave queue with proper error handling"""
        try:
            await interaction.response.defer(ephemeral=True)  # DEFER FIRST

            scrim_cog = self.bot.get_cog('ScrimCog')
            if not scrim_cog:
                await interaction.followup.send("❌ 내전 시스템을 찾을 수 없습니다.", ephemeral=True)
                return

            success, message = await scrim_cog.leave_queue(interaction.user.id, self.scrim_id)
            await interaction.followup.send(message, ephemeral=True)  # CHANGED from response.send

            if success:
                # Don't wait for message update - run in background
                asyncio.create_task(scrim_cog.update_scrim_message(interaction.message, self.scrim_id))

        except Exception as e:
            self.logger.error(f"Leave queue error: {e}")
            try:
                await interaction.followup.send("❌ 오류가 발생했습니다.", ephemeral=True)
            except:
                pass

    @discord.ui.button(
        label="취소",
        style=discord.ButtonStyle.danger,
        custom_id="cancel_scrim",
        emoji="🗑️"
    )
    async def cancel_scrim(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cancel scrim with proper error handling"""
        try:
            # DON'T defer here yet - we need to check permissions first
            scrim_cog = self.bot.get_cog('ScrimCog')
            if not scrim_cog:
                await interaction.response.send_message("❌ 내전 시스템을 찾을 수 없습니다.", ephemeral=True)
                return

            # Permission check
            is_organizer = interaction.user.id == self.scrim_data['organizer_id']
            is_staff = scrim_cog.has_staff_permissions(interaction.user)

            if not (is_organizer or is_staff):
                await interaction.response.send_message("❌ 이 내전을 취소할 권한이 없습니다.", ephemeral=True)
                return

            # NOW defer since we passed permission checks
            await interaction.response.defer(ephemeral=True)

            # Confirmation embed
            embed = discord.Embed(
                title="⚠️ 내전 취소 확인",
                description="이 내전을 정말 취소하시겠습니까?\n모든 참가자에게 알림이 전송됩니다.",
                color=discord.Color.red()
            )

            view = discord.ui.View(timeout=60)
            confirm_button = discord.ui.Button(label="확인", style=discord.ButtonStyle.danger)
            cancel_button = discord.ui.Button(label="취소", style=discord.ButtonStyle.secondary)

            async def confirm_callback(confirm_interaction):
                try:
                    await confirm_interaction.response.defer()  # DEFER in callback too
                    success = await scrim_cog.cancel_scrim(self.scrim_id, interaction.user.id)
                    if success:
                        await confirm_interaction.followup.send("✅ 내전이 취소되었습니다.", ephemeral=True)
                        # Update message in background
                        asyncio.create_task(scrim_cog.update_scrim_message(interaction.message, self.scrim_id))
                    else:
                        await confirm_interaction.followup.send("❌ 내전 취소 중 오류가 발생했습니다.", ephemeral=True)
                except Exception as e:
                    self.logger.error(f"Confirm cancel error: {e}")
                    try:
                        await confirm_interaction.followup.send("❌ 오류가 발생했습니다.", ephemeral=True)
                    except:
                        pass

            async def cancel_callback(cancel_interaction):
                try:
                    await cancel_interaction.response.send_message("취소되었습니다.", ephemeral=True)
                except Exception as e:
                    self.logger.error(f"Cancel callback error: {e}")

            confirm_button.callback = confirm_callback
            cancel_button.callback = cancel_callback
            view.add_item(confirm_button)
            view.add_item(cancel_button)

            await interaction.followup.send(embed=embed, view=view, ephemeral=True)  # CHANGED from response.send

        except Exception as e:
            self.logger.error(f"Cancel scrim error: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ 오류가 발생했습니다.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ 오류가 발생했습니다.", ephemeral=True)
            except:
                pass


class ScrimCreateView(discord.ui.View):
    """스타일이 개선된 지속적인 뷰"""

    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.logger = get_logger("내부 매치")

    @discord.ui.button(
        label="내전 생성",
        style=discord.ButtonStyle.primary,
        custom_id="create_scrim_improved",
        emoji="🎮"
    )
    async def create_scrim(self, interaction: discord.Interaction, button: discord.ui.Button):
        """개선된 내전 생성 프로세스 시작"""
        try:
            # CRITICAL: Defer immediately
            await interaction.response.defer(ephemeral=True)

            self.logger.info(f"Create scrim button pressed by {interaction.user.id}")

            if not config.is_feature_enabled(interaction.guild.id, 'scrim_system'):
                await interaction.followup.send(
                    "⚠ 이 서버에서 내전 시스템이 비활성화되어 있습니다.",
                    ephemeral=True
                )
                return

            game_view = GameSelectView(self.bot, interaction.guild.id)

            embed = discord.Embed(
                title="🎮 게임 선택",
                description="내전을 위한 게임을 선택하세요:",
                color=discord.Color.green()
            )
            embed.set_footer(text="아래 드롭다운을 사용하여 게임을 선택하세요")

            # Store the message reference for the new view
            message = await interaction.followup.send(embed=embed, view=game_view, ephemeral=True)
            game_view.message = message  # ADD THIS LINE

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
        self.scrims_data = {}  # 활성 내전을 위한 메모리 저장소
        self.scrims_file = "data/scrims.json"
        self.map_pools_file = "data/map_pools.json"
        self.map_pools = {}  # 길드 ID -> 맵 리스트

        # 기본 발로란트 맵 풀
        self.default_valorant_maps = [
            "바인드", "헤이븐", "스플릿", "어센트", "아이스박스",
            "브리즈", "프랙처", "펄", "로터스", "선셋", "어비스", "코라도"
        ]

        # 봇이 준비된 후 태스크 시작
        self.bot.loop.create_task(self.wait_and_start_tasks())

    async def wait_and_start_tasks(self):
        """봇이 준비될 때까지 기다린 후 태스크 시작"""
        await self.bot.wait_until_ready()
        await self.load_scrims_data()
        await self.load_map_pools()
        await self.setup_persistent_views()
        await self.setup_scrim_panels()

        # 알림 및 정리 태스크 시작
        self.scrim_notifications.start()
        self.cleanup_old_scrims.start()

    async def setup_persistent_views(self):
        """Setup persistent views on bot startup"""
        try:
            # Add persistent views to the bot
            self.bot.add_view(ScrimCreateView(self.bot))

            # For each active scrim, add its view
            for scrim_id, scrim_data in self.scrims_data.items():
                if scrim_data['status'] == '활성':
                    self.bot.add_view(ScrimView(self.bot, scrim_data))

            self.logger.info("Persistent views setup completed")
        except Exception as e:
            self.logger.error(f"Error setting up persistent views: {e}")

    def has_staff_permissions(self, member: discord.Member) -> bool:
        """멤버가 스태프 권한을 가지고 있는지 확인"""
        if member.guild_permissions.administrator:
            return True

        admin_role_id = config.get_role_id(member.guild.id, 'admin_role')
        if admin_role_id:
            admin_role = discord.utils.get(member.roles, id=admin_role_id)
            if admin_role:
                return True

        staff_role_id = config.get_role_id(member.guild.id, 'staff_role')
        if staff_role_id:
            staff_role = discord.utils.get(member.roles, id=staff_role_id)
            return staff_role is not None

        return False

    async def load_scrims_data(self):
        """내전 데이터 파일에서 로드"""
        try:
            if os.path.exists(self.scrims_file):
                with open(self.scrims_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 문자열 날짜를 datetime 객체로 변환
                    for scrim_id, scrim_data in data.items():
                        scrim_data['start_time'] = datetime.fromisoformat(scrim_data['start_time'])
                        scrim_data['created_at'] = datetime.fromisoformat(scrim_data['created_at'])
                    self.scrims_data = data
                self.logger.info("내전 데이터 로드 완료", extra={'guild_id': None})
        except Exception as e:
            self.logger.error(f"내전 데이터 로드 중 오류: {e}", extra={'guild_id': None})

    async def save_scrims_data(self):
        """내전 데이터를 파일에 저장 - 비동기 버전"""
        try:
            os.makedirs(os.path.dirname(self.scrims_file), exist_ok=True)

            data_to_save = {}
            for scrim_id, scrim_data in self.scrims_data.items():
                data_copy = scrim_data.copy()
                data_copy['start_time'] = scrim_data['start_time'].isoformat()
                data_copy['created_at'] = scrim_data['created_at'].isoformat()
                data_to_save[scrim_id] = data_copy

            # Use thread for file I/O to avoid blocking
            def write_file():
                with open(self.scrims_file, 'w', encoding='utf-8') as f:
                    json.dump(data_to_save, f, ensure_ascii=False, indent=2)

            await asyncio.to_thread(write_file)

        except Exception as e:
            self.logger.error(f"내전 데이터 저장 중 오류: {e}", extra={'guild_id': None})
    async def load_map_pools(self):
        """맵 풀 파일에서 로드"""
        try:
            if os.path.exists(self.map_pools_file):
                with open(self.map_pools_file, 'r', encoding='utf-8') as f:
                    # 문자열 키를 정수로 변환
                    data = json.load(f)
                    self.map_pools = {int(guild_id): maps for guild_id, maps in data.items()}
                self.logger.info("맵 풀 데이터 로드 완료", extra={'guild_id': None})
            else:
                self.map_pools = {}
        except Exception as e:
            self.logger.error(f"맵 풀 로드 중 오류: {e}", extra={'guild_id': None})
            self.map_pools = {}

    async def save_map_pools(self):
        """맵 풀을 파일에 저장"""
        try:
            os.makedirs(os.path.dirname(self.map_pools_file), exist_ok=True)
            # 정수 키를 문자열로 변환하여 JSON 저장
            data_to_save = {str(guild_id): maps for guild_id, maps in self.map_pools.items()}

            with open(self.map_pools_file, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"맵 풀 저장 중 오류: {e}", extra={'guild_id': None})

    def get_map_pool(self, guild_id: int) -> List[str]:
        """길드의 맵 풀 가져오기, 설정되지 않은 경우 기본값 반환"""
        return self.map_pools.get(guild_id, self.default_valorant_maps.copy())

    async def update_map_pool(self, guild_id: int, maps: List[str]) -> bool:
        """길드의 맵 풀 업데이트"""
        try:
            self.map_pools[guild_id] = maps
            await self.save_map_pools()
            self.logger.info(f"길드 {guild_id}의 맵 풀 업데이트: {maps}", extra={'guild_id': guild_id})
            return True
        except Exception as e:
            self.logger.error(f"길드 {guild_id}의 맵 풀 업데이트 중 오류: {e}", extra={'guild_id': guild_id})
            return False

    async def setup_scrim_panels(self):
        """설정된 채널에 내전 생성 패널 설정"""
        all_configs = config.get_all_server_configs()
        for guild_id_str, guild_config in all_configs.items():
            if guild_config.get('features', {}).get('scrim_system'):
                guild_id = int(guild_id_str)
                scrim_channel_id = config.get_channel_id(guild_id, 'scrim_channel')

                if scrim_channel_id:
                    channel = self.bot.get_channel(scrim_channel_id)
                    if channel:
                        await self.setup_scrim_panel(channel)

    async def setup_scrim_panel(self, channel: discord.TextChannel):
        """특정 채널에 내전 생성 패널 설정"""
        try:
            # 기존 패널 메시지 찾기
            async for message in channel.history(limit=50):
                if (message.author == self.bot.user and
                        message.embeds and
                        "내전 생성 패널" in message.embeds[0].title):
                    # 기존 메시지를 새로운 뷰로 업데이트
                    await message.edit(embed=self.create_scrim_panel_embed(), view=ScrimCreateView(self.bot))
                    self.logger.info(f"채널 {channel.id}의 기존 내전 패널 업데이트",
                                     extra={'guild_id': channel.guild.id})
                    return

            # 새로운 패널 생성
            embed = self.create_scrim_panel_embed()
            message = await channel.send(embed=embed, view=ScrimCreateView(self.bot))
            self.logger.info(f"채널 {channel.id}에 새로운 내전 패널 생성",
                             extra={'guild_id': channel.guild.id})

        except Exception as e:
            self.logger.error(f"채널 {channel.id}의 내전 패널 설정 중 오류: {e}",
                              extra={'guild_id': channel.guild.id})

    def create_scrim_panel_embed(self) -> discord.Embed:
        """개선된 내전 생성 패널 임베드 생성"""
        embed = discord.Embed(
            title="🎮 내전 생성 패널",
            description=(
                "**개선된 내전 시스템**에 오신 것을 환영합니다! 아래 버튼을 클릭하여 새 내전을 생성하세요.\n\n"
                "**✨ 새로운 기능:**\n"
                "• 역할 태그와 함께 쉬운 게임 선택\n"
                "• 빠른 시간 선택 옵션\n"
                "• 스마트 티어 범위 선택\n"
                "• 간소화된 플레이어 수 설정\n"
                "• 개선된 시각적 디자인\n\n"
                "**🎯 지원되는 게임:**\n"
                "• 발로란트 • 리그 오브 레전드 • 팀파이트 택틱스\n"
                "• 배틀그라운드 • 기타 게임\n\n"
                "내전을 생성할 준비가 되셨나요?"
            ),
            color=discord.Color.blue()
        )

        embed.set_footer(text="개선된 내전 시스템 v2.0 • 시작하려면 버튼을 클릭하세요!")
        return embed

    async def create_scrim(self, interaction: discord.Interaction, max_players: int):
        try:
            # Example logic: Save scrim data to self.scrims_data
            scrim_id = str(random.randint(100000, 999999))  # Generate ID
            scrim_data = {
                'guild_id': self.guild_id,
                'game': self.game,
                'gamemode': self.gamemode,
                'tier': self.tier,
                'start_time': self.start_time,
                'max_players': max_players,
                'role_id': self.role_id,
                'participants': [],
                'queue': [],
                'status': '활성',
                'channel_id': interaction.channel_id,
                # Add message_id if sending a new message
            }
            self.scrims_data[scrim_id] = scrim_data

            # Send confirmation embed
            embed = discord.Embed(
                title="✅ 내전 생성 완료",
                description=f"ID: {scrim_id}\n게임: {self.game}\n모드: {self.gamemode}\n티어: {self.tier}\n시작: {self.start_time.strftime('%Y-%m-%d %H:%M EST')}\n최대 플레이어: {max_players}",
                color=discord.Color.green()
            )
            role = interaction.guild.get_role(self.role_id)
            if role:
                await interaction.channel.send(f"{role.mention} 새 내전이 생성되었습니다!", embed=embed)
            else:
                await interaction.channel.send(embed=embed)

            # Clean up the selection message
            await interaction.edit_original_response(content="내전 생성이 완료되었습니다.", embed=None, view=None)

        except Exception as e:
            print(f"ERROR in create_scrim: {str(e)}\nFull traceback: {traceback.format_exc()}")
            self.logger.error(f"Scrim creation error: {traceback.format_exc()}")
            await interaction.followup.send(f"⚠ 내전 생성 중 오류가 발생했습니다: {str(e)}", ephemeral=True)

    async def post_scrim_message(self, channel: discord.TextChannel, scrim_id: str):
        """인터랙티브 버튼과 함께 내전 메시지 게시"""
        try:
            scrim_data = self.scrims_data.get(scrim_id)
            if not scrim_data:
                return

            embed = self.create_scrim_embed(scrim_data)
            view = ScrimView(self.bot, scrim_data)

            message = await channel.send(embed=embed, view=view)

            # 나중 업데이트를 위해 메시지 ID 저장
            scrim_data['message_id'] = message.id
            await self.save_scrims_data()

            self.logger.info(f"채널 {channel.id}에 내전 메시지 {scrim_id} 게시",
                             extra={'guild_id': channel.guild.id})

        except Exception as e:
            self.logger.error(f"내전 메시지 {scrim_id} 게시 중 오류: {e}",
                              extra={'guild_id': scrim_data.get('guild_id') if scrim_data else None})

    def create_scrim_embed(self, scrim_data: Dict) -> discord.Embed:
        """시각적으로 개선된 내전 임베드 생성"""
        eastern = pytz.timezone('America/New_York')

        # 필요 시 시작 시간을 시간대 인식으로 변환
        start_time = scrim_data['start_time']
        if start_time.tzinfo is None:
            start_time = eastern.localize(start_time)

        now = datetime.now(eastern)
        time_until_start = start_time - now

        # 상태 색상 및 이모지
        status_colors = {
            '활성': discord.Color.green(),
            '취소됨': discord.Color.red(),
            '완료됨': discord.Color.blue()
        }

        status_emojis = {
            '활성': '🟢',
            '취소됨': '🔴',
            '완료됨': '🔵'
        }

        color = status_colors.get(scrim_data['status'], discord.Color.green())
        status_emoji = status_emojis.get(scrim_data['status'], '🟢')

        # 게임 이모지 매핑
        game_emojis = {
            '발로란트': '🎯',
            '리그 오브 레전드': '⚔️',
            '팀파이트 택틱스': '♟️',
            '배틀그라운드': '🔫',
            '기타 게임': '🎮'
        }

        game_emoji = game_emojis.get(scrim_data['game'], '🎮')

        # 개선된 스타일로 임베드 생성
        embed = discord.Embed(
            title=f"{game_emoji} {scrim_data['game']} 내전",
            color=color,
            timestamp=datetime.now(timezone.utc)
        )

        # 더 나은 가시성을 위해 설명에 주요 정보 포함
        participants_count = len(scrim_data['participants'])
        max_players = scrim_data['max_players']
        queue_count = len(scrim_data['queue'])

        # 시작까지 남은 시간
        if scrim_data['status'] == '활성' and time_until_start.total_seconds() > 0:
            hours, remainder = divmod(int(time_until_start.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)
            time_text = f" • {hours}시간 {minutes}분 후 시작" if hours > 0 else f" • {minutes}분 후 시작"
        else:
            time_text = ""

        # 상태 텍스트
        status_texts = {
            '활성': f'{status_emoji} 활성 • 모집 중',
            '취소됨': f'{status_emoji} 취소됨',
            '완료됨': f'{status_emoji} 완료됨'
        }

        status_text = status_texts.get(scrim_data['status'], f'{status_emoji} 알 수 없음')

        embed.description = (
            f"**모드:** {scrim_data['gamemode']}\n"
            f"**티어 범위:** {scrim_data['tier_range']}\n"
            f"**시작 시간:** {start_time.strftime('%Y-%m-%d %H:%M EST')}{time_text}\n"
            f"**상태:** {status_text}\n"
            f"**플레이어:** {participants_count}/{max_players}"
            f"{' ✅' if participants_count >= max_players else ''}"
            f" • **대기열:** {queue_count}"
        )

        # 주최자 정보
        guild = self.bot.get_guild(scrim_data['guild_id'])
        organizer = guild.get_member(scrim_data['organizer_id']) if guild else None
        organizer_name = organizer.display_name if organizer else f"알 수 없음 ({scrim_data['organizer_id']})"

        embed.add_field(
            name="👑 주최자",
            value=organizer_name,
            inline=True
        )

        # 더 나은 형식의 참가자 목록
        if scrim_data['participants']:
            participant_names = []
            for i, user_id in enumerate(scrim_data['participants']):
                member = guild.get_member(user_id) if guild else None
                name = member.display_name if member else f"알 수 없음 ({user_id})"
                participant_names.append(f"`{i + 1}.` {name}")

            # 필드 길이 제한을 피하기 위해 청크로 나누기
            participant_text = "\n".join(participant_names)
            if len(participant_text) > 1000:
                participant_text = participant_text[:997] + "..."

            embed.add_field(
                name="📋 참가자",
                value=participant_text or "없음",
                inline=False
            )

        # 더 나은 형식의 대기열 목록
        if scrim_data['queue']:
            queue_names = []
            for i, user_id in enumerate(scrim_data['queue']):
                member = guild.get_member(user_id) if guild else None
                name = member.display_name if member else f"알 수 없음 ({user_id})"
                queue_names.append(f"`{i + 1}.` {name}")

            queue_text = "\n".join(queue_names)
            if len(queue_text) > 1000:
                queue_text = queue_text[:997] + "..."

            embed.add_field(
                name="⏳ 대기열",
                value=queue_text,
                inline=False
            )

        # 취소된 내전을 위한 특별 스타일링
        if scrim_data['status'] == '취소됨':
            embed.add_field(
                name="⚠️ 공지",
                value="이 내전이 취소되었습니다.",
                inline=False
            )

        # 내전 ID가 포함된 푸터
        embed.set_footer(
            text=f"내전 ID: {scrim_data['id']} • 개선된 내전 시스템 v2.0"
        )

        return embed

    async def join_scrim(self, user_id: int, scrim_id: str) -> tuple[bool, str]:
        """사용자를 내전 참가자에 추가"""
        try:
            scrim_data = self.scrims_data.get(scrim_id)
            if not scrim_data:
                return False, "❌ 내전을 찾을 수 없습니다."

            if scrim_data['status'] != '활성':
                return False, "❌ 이 내전은 더 이상 활성 상태가 아닙니다."

            # 이미 참가 중인지 확인
            if user_id in scrim_data['participants']:
                return False, "❌ 이미 참가 중입니다."

            # 대기열에 있으면 제거
            if user_id in scrim_data['queue']:
                scrim_data['queue'].remove(user_id)

            # 내전이 꽉 찼는지 확인
            if len(scrim_data['participants']) >= scrim_data['max_players']:
                return False, "❌ 내전이 꽉 찼습니다. 대기열에 가입해주세요."

            # 참가자에 추가
            scrim_data['participants'].append(user_id)
            await self.save_scrims_data()

            self.logger.info(f"사용자 {user_id}가 내전 {scrim_id}에 참가",
                             extra={'guild_id': scrim_data['guild_id']})
            return True, "✅ 내전에 성공적으로 참가했습니다!"

        except Exception as e:
            self.logger.error(f"내전 {scrim_id} 참가 중 오류: {e}",
                              extra={'guild_id': scrim_data.get('guild_id') if scrim_data else None})
            return False, "❌ 내전 참가 중 오류가 발생했습니다."

    async def leave_scrim(self, user_id: int, scrim_id: str) -> tuple[bool, str]:
        """사용자를 내전 참가자에서 제거"""
        try:
            scrim_data = self.scrims_data.get(scrim_id)
            if not scrim_data:
                return False, "❌ 내전을 찾을 수 없습니다."

            if user_id not in scrim_data['participants']:
                return False, "❌ 참가 중이 아닙니다."

            # 참가자에서 제거
            scrim_data['participants'].remove(user_id)

            # 대기열에서 첫 번째 사람을 참가자로 이동 (공간이 있는 경우)
            if scrim_data['queue'] and len(scrim_data['participants']) < scrim_data['max_players']:
                next_user = scrim_data['queue'].pop(0)
                scrim_data['participants'].append(next_user)

                # 대기열에서 참가자로 이동된 사용자에게 알림 시도
                guild = self.bot.get_guild(scrim_data['guild_id'])
                if guild:
                    member = guild.get_member(next_user)
                    if member:
                        try:
                            embed = discord.Embed(
                                title="🎮 내전 참가 확정",
                                description=f"**{scrim_data['game']}** 내전에 자리가 생겨 대기열에서 자동으로 이동되었습니다!",
                                color=discord.Color.green()
                            )
                            await member.send(embed=embed)
                        except:
                            pass  # DM 전송 불가, 문제 없음

            await self.save_scrims_data()

            self.logger.info(f"사용자 {user_id}가 내전 {scrim_id}에서 나감",
                             extra={'guild_id': scrim_data['guild_id']})
            return True, "✅ 내전에서 성공적으로 나갔습니다."

        except Exception as e:
            self.logger.error(f"내전 {scrim_id} 나가기 중 오류: {e}",
                              extra={'guild_id': scrim_data.get('guild_id') if scrim_data else None})
            return False, "❌ 내전 나가기 중 오류가 발생했습니다."

    async def join_queue(self, user_id: int, scrim_id: str) -> tuple[bool, str]:
        """사용자를 내전 대기열에 추가"""
        try:
            scrim_data = self.scrims_data.get(scrim_id)
            if not scrim_data:
                return False, "❌ 내전을 찾을 수 없습니다."

            if scrim_data['status'] != '활성':
                return False, "❌ 이 내전은 더 이상 활성 상태가 아닙니다."

            # 이미 대기열에 있는지 확인
            if user_id in scrim_data['queue']:
                return False, "❌ 이미 대기열에 있습니다."

            # 이미 참가 중인지 확인
            if user_id in scrim_data['participants']:
                return False, "❌ 이미 참가 중입니다."

            # 주요 참가자에 공간이 있는지 확인
            if len(scrim_data['participants']) < scrim_data['max_players']:
                return False, "❌ 아직 자리가 남아 있습니다. 직접 참가해주세요."

            # 대기열에 추가
            scrim_data['queue'].append(user_id)
            await self.save_scrims_data()

            queue_position = len(scrim_data['queue'])
            self.logger.info(f"사용자 {user_id}가 내전 {scrim_id}의 대기열에 {queue_position}번으로 가입",
                             extra={'guild_id': scrim_data['guild_id']})
            return True, f"✅ 대기열에 성공적으로 가입했습니다! (위치: {queue_position})"

        except Exception as e:
            self.logger.error(f"내전 {scrim_id} 대기열 가입 중 오류: {e}",
                              extra={'guild_id': scrim_data.get('guild_id') if scrim_data else None})
            return False, "❌ 대기열 가입 중 오류가 발생했습니다."

    async def leave_queue(self, user_id: int, scrim_id: str) -> tuple[bool, str]:
        """사용자를 내전 대기열에서 제거"""
        try:
            scrim_data = self.scrims_data.get(scrim_id)
            if not scrim_data:
                return False, "❌ 내전을 찾을 수 없습니다."

            if user_id not in scrim_data['queue']:
                return False, "❌ 대기열에 없습니다."

            # 대기열에서 제거
            scrim_data['queue'].remove(user_id)
            await self.save_scrims_data()

            self.logger.info(f"사용자 {user_id}가 내전 {scrim_id}의 대기열에서 나감",
                             extra={'guild_id': scrim_data['guild_id']})
            return True, "✅ 대기열에서 성공적으로 나갔습니다."

        except Exception as e:
            self.logger.error(f"내전 {scrim_id} 대기열 나가기 중 오류: {e}",
                              extra={'guild_id': scrim_data.get('guild_id') if scrim_data else None})
            return False, "❌ 대기열 나가기 중 오류가 발생했습니다."

    async def cancel_scrim(self, scrim_id: str, canceller_id: int) -> bool:
        """내전 취소"""
        try:
            scrim_data = self.scrims_data.get(scrim_id)
            if not scrim_data:
                return False

            scrim_data['status'] = '취소됨'
            await self.save_scrims_data()

            # 모든 참가자와 대기열 멤버에게 알림
            guild = self.bot.get_guild(scrim_data['guild_id'])
            if guild:
                all_users = set(scrim_data['participants'] + scrim_data['queue'])
                canceller = guild.get_member(canceller_id)
                canceller_name = canceller.display_name if canceller else "관리자"

                for user_id in all_users:
                    member = guild.get_member(user_id)
                    if member:
                        try:
                            embed = discord.Embed(
                                title="❌ 내전 취소 공지",
                                description=f"**{scrim_data['game']}** 내전이 취소되었습니다.",
                                color=discord.Color.red()
                            )
                            embed.add_field(name="취소자", value=canceller_name, inline=True)
                            embed.add_field(name="원래 시작 시간",
                                            value=scrim_data['start_time'].strftime("%Y-%m-%d %H:%M EST"),
                                            inline=True)
                            await member.send(embed=embed)
                        except:
                            pass  # DM 전송 불가, 문제 없음

            self.logger.info(f"사용자 {canceller_id}가 내전 {scrim_id} 취소",
                             extra={'guild_id': scrim_data['guild_id']})
            return True

        except Exception as e:
            self.logger.error(f"내전 {scrim_id} 취소 중 오류: {e}",
                              extra={'guild_id': scrim_data.get('guild_id') if scrim_data else None})
            return False

    async def update_scrim_message(self, message: discord.Message, scrim_id: str):
        """현재 데이터로 내전 메시지 업데이트"""
        try:
            scrim_data = self.scrims_data.get(scrim_id)
            if not scrim_data:
                return

            embed = self.create_scrim_embed(scrim_data)
            view = ScrimView(self.bot, scrim_data)

            await message.edit(embed=embed, view=view)

        except Exception as e:
            self.logger.error(f"내전 메시지 {scrim_id} 업데이트 중 오류: {e}",
                              extra={'guild_id': scrim_data.get('guild_id') if scrim_data else None})

    @tasks.loop(minutes=1)
    async def scrim_notifications(self):
        """내전 시작 시간 전에 알림 전송"""
        try:
            eastern = pytz.timezone('America/New_York')
            now = datetime.now(eastern)

            for scrim_id, scrim_data in self.scrims_data.items():
                if scrim_data['status'] != '활성':
                    continue

                start_time = scrim_data['start_time']
                if start_time.tzinfo is None:
                    start_time = eastern.localize(start_time)

                time_until_start = start_time - now

                # 알림을 위한 내전이 꽉 찼는지 확인
                is_full = len(scrim_data['participants']) >= scrim_data['max_players']

                # 10분 알림
                if (5 <= time_until_start.total_seconds() / 60 <= 15 and
                        not scrim_data['notifications_sent']['10min'] and is_full):
                    await self.send_scrim_notification(scrim_data, "10min")
                    scrim_data['notifications_sent']['10min'] = True
                    await self.save_scrims_data()

                # 2분 알림
                elif (0 <= time_until_start.total_seconds() / 60 <= 5 and
                      not scrim_data['notifications_sent']['2min'] and is_full):
                    await self.send_scrim_notification(scrim_data, "2min")
                    scrim_data['notifications_sent']['2min'] = True
                    await self.save_scrims_data()

                # 시작 시간이 지난 경우 완료로 표시
                elif time_until_start.total_seconds() <= 0 and scrim_data['status'] == '활성':
                    scrim_data['status'] = '완료됨'
                    await self.save_scrims_data()

                    # 메시지가 존재하는 경우 내전 메시지 업데이트
                    if 'message_id' in scrim_data:
                        guild = self.bot.get_guild(scrim_data['guild_id'])
                        if guild:
                            channel = guild.get_channel(scrim_data['channel_id'])
                            if channel:
                                try:
                                    message = await channel.fetch_message(scrim_data['message_id'])
                                    await self.update_scrim_message(message, scrim_id)
                                except:
                                    pass

        except Exception as e:
            self.logger.error(f"내전 알림 태스크 중 오류: {e}", extra={'guild_id': None})

    async def send_scrim_notification(self, scrim_data: Dict, notification_type: str):
        """내전 참가자에게 알림 전송"""
        try:
            guild = self.bot.get_guild(scrim_data['guild_id'])
            if not guild:
                return

            # 시간 텍스트
            time_text = "10분" if notification_type == "10min" else "2분"

            # 멘션 리스트 생성
            mentions = []
            for user_id in scrim_data['participants']:
                mentions.append(f"<@{user_id}>")

            if not mentions:
                return

            # 알림 임베드 생성
            embed = discord.Embed(
                title=f"⏰ 내전이 {time_text} 후 시작됩니다",
                description=f"**{scrim_data['game']}** 내전이 곧 시작됩니다!",
                color=discord.Color.orange()
            )
            embed.add_field(name="게임 모드", value=scrim_data['gamemode'], inline=True)
            embed.add_field(name="시작 시간", value=scrim_data['start_time'].strftime("%H:%M EST"), inline=True)
            embed.add_field(name="참가자", value=f"{len(scrim_data['participants'])}/{scrim_data['max_players']}",
                            inline=True)

            # 채널에 전송
            channel = guild.get_channel(scrim_data['channel_id'])
            if channel:
                mention_text = " ".join(mentions)
                await channel.send(content=mention_text, embed=embed)

            self.logger.info(f"내전 {scrim_data['id']}에 대한 {notification_type} 알림 전송",
                             extra={'guild_id': scrim_data['guild_id']})

        except Exception as e:
            self.logger.error(f"내전 알림 전송 중 오류: {e}",
                              extra={'guild_id': scrim_data.get('guild_id')})

    @tasks.loop(hours=6)
    async def cleanup_old_scrims(self):
        """오래된 완료/취소된 내전 정리"""
        try:
            eastern = pytz.timezone('America/New_York')
            now = datetime.now(eastern)
            cutoff_time = now - timedelta(days=7)  # 7일 동안 내전 유지

            scrims_to_remove = []
            for scrim_id, scrim_data in self.scrims_data.items():
                start_time = scrim_data['start_time']
                if start_time.tzinfo is None:
                    start_time = eastern.localize(start_time)

                # 오래된 완료/취소된 내전 제거
                if (scrim_data['status'] in ['완료됨', '취소됨'] and
                        start_time < cutoff_time):
                    scrims_to_remove.append(scrim_id)

            for scrim_id in scrims_to_remove:
                del self.scrims_data[scrim_id]
                self.logger.info(f"오래된 내전 {scrim_id} 정리", extra={'guild_id': None})

            if scrims_to_remove:
                await self.save_scrims_data()
                self.logger.info(f"{len(scrims_to_remove)}개의 오래된 내전 정리", extra={'guild_id': None})

        except Exception as e:
            self.logger.error(f"정리 태스크 중 오류: {e}", extra={'guild_id': None})

    # 슬래시 명령어
    @app_commands.command(name="맵선택", description="활성 맵 풀에서 무작위 맵을 선택합니다.")
    @app_commands.describe(count="선택할 맵의 수 (기본값: 1)")
    async def random_map(self, interaction: discord.Interaction, count: Optional[int] = 1):
        # 기능 활성화 여부 확인
        if not config.is_feature_enabled(interaction.guild.id, 'scrim_system'):
            await interaction.response.send_message(
                "❌ 이 서버에서 내전 시스템이 비활성화되어 있습니다.",
                ephemeral=True
            )
            return

        # 수량 유효성 검사
        if count < 1 or count > 10:
            await interaction.response.send_message("❌ 맵 수는 1-10 사이여야 합니다.", ephemeral=True)
            return

        guild_id = interaction.guild.id
        map_pool = self.get_map_pool(guild_id)

        if not map_pool:
            await interaction.response.send_message("❌ 이 서버에 맵 풀이 설정되지 않았습니다.", ephemeral=True)
            return

        # 사용 가능한 맵보다 더 많은 맵을 선택하지 않도록
        if count > len(map_pool):
            count = len(map_pool)

        # 무작위 맵 선택
        selected_maps = random.sample(map_pool, count)

        embed = discord.Embed(
            title="🎯 무작위 맵 선택",
            color=discord.Color.green()
        )

        if count == 1:
            embed.description = f"**선택된 맵:** {selected_maps[0]}"
        else:
            map_list = "\n".join([f"{i + 1}. **{map_name}**" for i, map_name in enumerate(selected_maps)])
            embed.description = f"**선택된 맵:**\n{map_list}"

        embed.add_field(name="총 맵 풀", value=f"{len(map_pool)} 맵", inline=True)
        embed.set_footer(text=f"{interaction.user.display_name}의 요청")

        await interaction.response.send_message(embed=embed)

        self.logger.info(f"무작위 맵 선택: {selected_maps} (길드 {guild_id})",
                         extra={'guild_id': guild_id})

    @app_commands.command(name="맵풀설정", description="서버의 맵 풀을 설정합니다. (관리자 전용)")
    @app_commands.default_permissions(administrator=True)
    async def set_map_pool(self, interaction: discord.Interaction):
        try:
            guild_id = interaction.guild.id
            current_maps = self.get_map_pool(guild_id)

            # 맵 풀 설정을 위한 모달 표시
            modal = MapPoolModal(self.bot, guild_id, current_maps)
            await interaction.response.send_modal(modal)

        except Exception as e:
            self.logger.error(f"set_map_pool 명령어에서 오류: {e}", extra={'guild_id': interaction.guild.id})
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ 맵 풀 설정 중 오류가 발생했습니다.", ephemeral=True)
            else:
                await interaction.followup.send("❌ 맵 풀 설정 중 오류가 발생했습니다.", ephemeral=True)

    @app_commands.command(name="맵풀확인", description="현재 서버의 맵 풀을 표시합니다.")
    async def show_map_pool(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id
        map_pool = self.get_map_pool(guild_id)

        embed = discord.Embed(
            title="🗺️ 현재 맵 풀",
            color=discord.Color.blue()
        )

        if map_pool:
            map_list = "\n".join([f"{i + 1}. **{map_name}**" for i, map_name in enumerate(map_pool)])
            embed.description = f"**총 {len(map_pool)} 맵:**\n{map_list}"

            if map_pool == self.default_valorant_maps:
                embed.set_footer(text="기본 발로란트 맵 풀 사용 중")
            else:
                embed.set_footer(text="사용자 지정 맵 풀 사용 중")
        else:
            embed.description = "설정된 맵이 없습니다."
            embed.color = discord.Color.red()

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="내전기록", description="활성 내전을 확인합니다.")
    async def list_scrims(self, interaction: discord.Interaction):
        # 기능 활성화 여부 확인
        if not config.is_feature_enabled(interaction.guild.id, 'scrim_system'):
            await interaction.response.send_message(
                "❌ 이 서버에서 내전 시스템이 비활성화되어 있습니다.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        guild_id = interaction.guild.id
        active_scrims = [
            scrim_data for scrim_data in self.scrims_data.values()
            if scrim_data['guild_id'] == guild_id and scrim_data['status'] == '활성'
        ]

        if not active_scrims:
            await interaction.followup.send("현재 활성 내전이 없습니다.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🎮 활성 내전",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc)
        )

        eastern = pytz.timezone('America/New_York')
        now = datetime.now(eastern)

        for scrim_data in sorted(active_scrims, key=lambda x: x['start_time']):
            start_time = scrim_data['start_time']
            if start_time.tzinfo is None:
                start_time = eastern.localize(start_time)

            time_until = start_time - now
            if time_until.total_seconds() > 0:
                hours, remainder = divmod(int(time_until.total_seconds()), 3600)
                minutes, _ = divmod(remainder, 60)
                time_text = f"{hours}시간 {minutes}분" if hours > 0 else f"{minutes}분"
            else:
                time_text = "진행 중"

            participants_count = len(scrim_data['participants'])
            max_players = scrim_data['max_players']
            queue_count = len(scrim_data['queue'])

            embed.add_field(
                name=f"{scrim_data['game']} ({scrim_data['gamemode']})",
                value=f"시작: {start_time.strftime('%H:%M')} ({time_text})\n"
                      f"플레이어: {participants_count}/{max_players}\n"
                      f"대기열: {queue_count}",
                inline=True
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="내전설정", description="내전 시스템 설정을 구성합니다. (관리자 전용)")
    @app_commands.describe(
        feature_enabled="내전 시스템 활성화/비활성화",
        scrim_channel="내전 생성 패널이 표시될 채널"
    )
    @app_commands.default_permissions(administrator=True)
    async def configure_scrim(self, interaction: discord.Interaction,
                              feature_enabled: Optional[bool] = None,
                              scrim_channel: Optional[discord.TextChannel] = None):

        guild_id = interaction.guild.id
        await interaction.response.defer(ephemeral=True)

        # 현재 설정 가져오기
        current_config = config.load_server_config(guild_id)
        features = current_config.get('features', {})
        channels = current_config.get('channels', {})

        updated = False

        # 기능 설정 업데이트
        if feature_enabled is not None:
            features['scrim_system'] = feature_enabled
            updated = True
            self.logger.info(f"내전 시스템이 길드 {guild_id}에서 {'활성화됨' if feature_enabled else '비활성화됨'}",
                             extra={'guild_id': guild_id})

        # 내전 채널 업데이트
        if scrim_channel is not None:
            channels['scrim_channel'] = {'id': scrim_channel.id, 'name': scrim_channel.name}
            updated = True
            self.logger.info(f"내전 채널이 #{scrim_channel.name} ({scrim_channel.id})로 길드 {guild_id}에 설정됨",
                             extra={'guild_id': guild_id})

        if updated:
            current_config['features'] = features
            current_config['channels'] = channels
            config.save_server_config(guild_id, current_config)
            await interaction.followup.send("✅ 내전 시스템 설정이 성공적으로 업데이트되었습니다.")

            # 채널이 설정되고 기능이 활성화된 경우 내전 패널 설정
            if scrim_channel is not None and features.get('scrim_system'):
                await self.setup_scrim_panel(scrim_channel)
        else:
            await interaction.followup.send("ℹ️ 설정에 변경 사항이 없습니다.")

    @app_commands.command(name="내전강제취소", description="내전을 강제로 취소합니다. (스태프 전용)")
    @app_commands.describe(scrim_id="취소할 내전의 ID")
    async def force_cancel_scrim(self, interaction: discord.Interaction, scrim_id: str):
        # 권한 확인
        if not self.has_staff_permissions(interaction.user):
            await interaction.response.send_message("❌ 이 명령어를 사용할 권한이 없습니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        scrim_data = self.scrims_data.get(scrim_id)
        if not scrim_data:
            await interaction.followup.send("❌ 내전을 찾을 수 없습니다.", ephemeral=True)
            return

        if scrim_data['guild_id'] != interaction.guild.id:
            await interaction.followup.send("❌ 이 내전은 이 서버에 속하지 않습니다.", ephemeral=True)
            return

        success = await self.cancel_scrim(scrim_id, interaction.user.id)
        if success:
            await interaction.followup.send(f"✅ 내전 `{scrim_id}`이(가) 취소되었습니다.", ephemeral=True)

            # 메시지가 존재하는 경우 메시지 업데이트 시도
            if 'message_id' in scrim_data:
                try:
                    channel = interaction.guild.get_channel(scrim_data['channel_id'])
                    if channel:
                        message = await channel.fetch_message(scrim_data['message_id'])
                        await self.update_scrim_message(message, scrim_id)
                except:
                    pass
        else:
            await interaction.followup.send("❌ 내전 취소 중 오류가 발생했습니다.", ephemeral=True)

    @app_commands.command(name="내전엠베드",
                          description="내전 패널 메시지를 새로 고치고 맨 아래에 다시 게시합니다. (스태프 전용)")
    @app_commands.default_permissions(administrator=True)
    async def refresh_scrim_panel(self, interaction: discord.Interaction):
        # 인터랙션 응답 지연
        await interaction.response.defer(ephemeral=True)

        guild_id = interaction.guild.id
        scrim_channel_id = config.get_channel_id(guild_id, 'scrim_channel')

        if not scrim_channel_id:
            await interaction.followup.send("❌ 내전 채널이 설정되지 않았습니다.", ephemeral=True)
            return

        channel = interaction.guild.get_channel(scrim_channel_id)
        if not channel:
            await interaction.followup.send("❌ 내전 채널을 찾을 수 없습니다.", ephemeral=True)
            return

        # 이전 내전 패널 메시지 삭제
        deleted_count = 0
        async for message in channel.history(limit=50):
            if message.author == self.bot.user and message.embeds and "내전 생성 패널" in message.embeds[0].title:
                try:
                    await message.delete()
                    deleted_count += 1
                except discord.errors.NotFound:
                    continue  # 메시지가 이미 삭제됨, 계속 진행
                except Exception as e:
                    self.logger.error(f"이전 내전 패널 메시지 삭제 중 오류: {e}",
                                      extra={'guild_id': guild_id})
                    await interaction.followup.send("❌ 이전 메시지 삭제 중 오류가 발생했습니다.", ephemeral=True)
                    return

        # 새 내전 패널 게시
        await self.setup_scrim_panel(channel)

        # 사용자에게 확인
        await interaction.followup.send("✅ 내전 패널이 성공적으로 새로 고쳐졌습니다.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(ScrimCog(bot))