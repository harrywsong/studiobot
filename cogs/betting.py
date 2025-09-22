# cogs/betting_v2.py
from typing import Optional, Dict, List
import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
from datetime import datetime, timezone, timedelta
import json
import os

from utils.logger import get_logger
from utils import config

# 상수
BETTING_CONTROL_CHANNEL_ID = 1419346557232484352
BETTING_CATEGORY_ID = 1417712502220783716


class SimpleBettingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("베팅시스템")
        self.logger.info("베팅 시스템 초기화 중...")

        # 초기화 작업 시작
        self.bot.loop.create_task(self.initialize())

    async def initialize(self):
        """베팅 시스템 초기화"""
        await self.bot.wait_until_ready()
        await self.setup_database()
        self.cleanup_task.start()
        await self.setup_control_panel()
        self.logger.info("베팅 시스템 준비 완료!")

    async def setup_database(self):
        """데이터베이스 테이블 생성"""
        try:
            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS betting_events_v2 (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    options JSONB NOT NULL,
                    creator_id BIGINT NOT NULL,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    ends_at TIMESTAMPTZ,
                    channel_id BIGINT,
                    message_id BIGINT,
                    winner_option INTEGER
                )
            """)

            await self.bot.pool.execute("""
                CREATE TABLE IF NOT EXISTS betting_bets_v2 (
                    id SERIAL PRIMARY KEY,
                    event_id INTEGER REFERENCES betting_events_v2(id) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL,
                    guild_id BIGINT NOT NULL,
                    option_index INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    placed_at TIMESTAMPTZ DEFAULT NOW(),
                    payout INTEGER DEFAULT 0
                )
            """)

            self.logger.info("데이터베이스 설정 완료")
        except Exception as e:
            self.logger.error(f"데이터베이스 설정 실패: {e}")

    async def setup_control_panel(self):
        """제어판 설정"""
        try:
            channel = self.bot.get_channel(BETTING_CONTROL_CHANNEL_ID)
            if not channel:
                return

            # 기존 메시지 정리
            async for message in channel.history(limit=10):
                if message.author == self.bot.user:
                    try:
                        await message.delete()
                    except:
                        pass

            embed = discord.Embed(
                title="🎲 베팅 제어판",
                description="아래 버튼을 클릭하여 새로운 베팅 이벤트를 생성하세요.",
                color=discord.Color.gold()
            )

            view = CreateBettingView()
            message = await channel.send(embed=embed, view=view)
            self.bot.add_view(view, message_id=message.id)

            self.logger.info("제어판 설정 완료")
        except Exception as e:
            self.logger.error(f"제어판 설정 실패: {e}")

    def has_admin_permissions(self, member: discord.Member) -> bool:
        """관리자 권한 확인"""
        return member.guild_permissions.administrator

    # Replace the existing create_betting_event method with this updated version

    async def create_betting_event_with_end_time(self, guild_id: int, title: str, options: List[str],
                                                 creator_id: int, end_time: datetime) -> Dict:
        """새로운 베팅 이벤트 생성 (특정 종료 시간으로)"""
        try:
            # 채널 생성
            guild = self.bot.get_guild(guild_id)
            category = guild.get_channel(BETTING_CATEGORY_ID)
            reference_channel = guild.get_channel(BETTING_CONTROL_CHANNEL_ID)

            channel_name = f"▫ 📋│베팅-{title.replace(' ', '-')[:20]}"
            betting_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                topic=f"베팅: {title}"
            )

            # 채널 위치 조정 (기준 채널 바로 아래에 배치)
            if reference_channel and reference_channel.category_id == category.id:
                try:
                    await betting_channel.edit(position=reference_channel.position + 1)
                except discord.HTTPException:
                    self.logger.warning("채널 위치 조정 실패")

            # 권한 설정
            await betting_channel.set_permissions(
                guild.default_role,
                send_messages=False,
                add_reactions=False
            )

            # 데이터베이스에 삽입 (end_time을 직접 사용)
            event_id = await self.bot.pool.fetchval("""
                INSERT INTO betting_events_v2 
                (guild_id, title, options, creator_id, ends_at, channel_id)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
            """, guild_id, title, json.dumps(options), creator_id, end_time, betting_channel.id)

            # 베팅 메시지 생성
            await self.create_betting_message(event_id, betting_channel)

            return {
                'success': True,
                'event_id': event_id,
                'channel_id': betting_channel.id,
                'ends_at': end_time
            }

        except Exception as e:
            self.logger.error(f"베팅 이벤트 생성 실패: {e}")
            return {'success': False, 'reason': str(e)}

    async def create_betting_message(self, event_id: int, channel: discord.TextChannel):
        """채널에 베팅 메시지 생성"""
        try:
            # 이벤트 데이터 가져오기
            event = await self.bot.pool.fetchrow("""
                SELECT * FROM betting_events_v2 WHERE id = $1
            """, event_id)

            if not event:
                return

            options = json.loads(event['options'])

            # 임베드 생성
            embed = await self.create_betting_embed(event_id, options, event)

            # 정적 버튼이 있는 뷰 생성
            view = BettingEventView(event_id, options)

            # 버튼 레이블을 옵션 이름으로 업데이트
            for i, child in enumerate(view.children):
                if hasattr(child, 'custom_id') and child.custom_id.startswith('bet_'):
                    option_index = int(child.custom_id.split('_')[1])
                    if option_index < len(options):
                        option_name = options[option_index][:15]  # 길이 제한
                        child.label = f"{option_index + 1}. {option_name}"
                        child.disabled = False
                    else:
                        child.disabled = True
                        child.style = discord.ButtonStyle.gray

            message = await channel.send(embed=embed, view=view)

            # 데이터베이스에 메시지 ID 업데이트
            await self.bot.pool.execute("""
                UPDATE betting_events_v2 SET message_id = $1 WHERE id = $2
            """, message.id, event_id)

            # 뷰 등록
            self.bot.add_view(view, message_id=message.id)

            self.logger.info(f"이벤트 {event_id} 베팅 메시지 생성 완료")

        except Exception as e:
            self.logger.error(f"베팅 메시지 생성 실패: {e}")

    async def create_betting_embed(self, event_id: int, options: List[str], event) -> discord.Embed:
        """베팅 임베드 생성 (플레이어 목록 포함)"""
        # 베팅 통계 가져오기
        stats = await self.bot.pool.fetch("""
            SELECT option_index, COUNT(*) as bets, SUM(amount) as total
            FROM betting_bets_v2 
            WHERE event_id = $1
            GROUP BY option_index
            ORDER BY option_index
        """, event_id)

        # 각 옵션별 베팅한 플레이어 목록 가져오기
        player_bets = await self.bot.pool.fetch("""
            SELECT option_index, user_id, amount
            FROM betting_bets_v2 
            WHERE event_id = $1
            ORDER BY option_index, amount DESC
        """, event_id)

        # 상태에 따른 제목과 색상 설정
        if event['status'] == 'active':
            title = f"🎲 {event['title']}"
            description = "옵션을 선택하고 베팅하세요!"
            color = discord.Color.gold()
        elif event['status'] == 'closed':
            title = f"⏸️ {event['title']} - 베팅 마감"
            description = "베팅이 마감되었습니다. 결과 발표를 기다려주세요!"
            color = discord.Color.orange()
        else:
            title = f"🏆 {event['title']} - 종료"
            description = "베팅이 종료되었습니다!"
            color = discord.Color.green()

        embed = discord.Embed(
            title=title,
            description=description,
            color=color
        )

        # 통계 계산
        total_pool = sum(stat['total'] or 0 for stat in stats)
        unique_bettors = await self.bot.pool.fetchval("""
            SELECT COUNT(DISTINCT user_id) FROM betting_bets_v2 WHERE event_id = $1
        """, event_id) or 0

        # 옵션별 플레이어 목록 정리
        players_by_option = {}
        for bet in player_bets:
            option_idx = bet['option_index']
            if option_idx not in players_by_option:
                players_by_option[option_idx] = []
            players_by_option[option_idx].append({
                'user_id': bet['user_id'],
                'amount': bet['amount']
            })

        # 옵션별 정보 표시
        option_text = ""
        for i, option in enumerate(options):
            # 해당 옵션의 통계 찾기
            option_stats = next((s for s in stats if s['option_index'] == i), None)
            bets_count = option_stats['bets'] if option_stats else 0
            amount = option_stats['total'] if option_stats else 0

            percentage = (amount / total_pool * 100) if total_pool > 0 else 0

            # 예상 배당률 계산
            payout_ratio = (total_pool / amount) if amount > 0 else 2.0

            # 진행 바 생성
            bar_length = 10
            filled = int(percentage / 10) if percentage <= 100 else 10
            bar = "█" * filled + "░" * (bar_length - filled)

            option_text += f"**{i + 1}. {option}**\n"
            option_text += f"💰 **{amount:,}** 코인 ({bets_count}명) - **{percentage:.1f}%**\n"
            option_text += f"📊 {bar} **{percentage:.1f}%**\n"

            if event['status'] in ['active', 'closed']:
                option_text += f"💸 예상 배당률: **x{payout_ratio:.2f}**\n"

            # 플레이어 목록 추가
            if i in players_by_option:
                players = players_by_option[i]
                player_list = []

                # 최대 5명까지만 표시 (너무 길어지지 않도록)
                display_limit = 5
                for j, player in enumerate(players[:display_limit]):
                    try:
                        user = self.bot.get_user(player['user_id'])
                        username = user.display_name if user else f"User#{player['user_id']}"
                        # 사용자명이 너무 길면 줄임
                        if len(username) > 12:
                            username = username[:10] + ".."
                        player_list.append(f"{username}({player['amount']:,})")
                    except:
                        player_list.append(f"User#{player['user_id']}({player['amount']:,})")

                # 더 많은 플레이어가 있으면 표시
                if len(players) > display_limit:
                    player_list.append(f"외 {len(players) - display_limit}명")

                if player_list:
                    option_text += f"👥 **베팅한 플레이어**: {', '.join(player_list)}\n"

            option_text += "\n"

        if not option_text.strip():
            option_text = "아직 베팅이 없습니다.\n"
            for i, option in enumerate(options):
                option_text += f"**{i + 1}. {option}**\n💰 0 코인 (0명) - 0.0%\n📊 ░░░░░░░░░░ 0.0%\n💸 예상 배당률: x2.00\n\n"

        embed.add_field(name="🎯 베팅 현황", value=option_text, inline=False)

        # 전체 통계
        embed.add_field(name="📊 전체 현황",
                        value=f"총 베팅액: **{total_pool:,}** 코인\n참여자: **{unique_bettors}**명",
                        inline=True)

        if event['status'] == 'active':
            embed.add_field(name="⏰ 종료 시간",
                            value=f"<t:{int(event['ends_at'].timestamp())}:R>",
                            inline=True)
            embed.set_footer(text="아래 버튼을 클릭하여 베팅하세요 | 한 사람당 하나의 옵션에만 베팅 가능")
        elif event['status'] == 'closed':
            embed.set_footer(text="베팅이 마감되어 더 이상 새로운 베팅을 받지 않습니다")
        else:
            embed.set_footer(text="베팅이 종료되었습니다")

        return embed
    async def get_user_bet(self, user_id: int, event_id: int) -> Optional[Dict]:
        """사용자의 기존 베팅 확인"""
        bet = await self.bot.pool.fetchrow("""
            SELECT option_index, amount FROM betting_bets_v2 
            WHERE user_id = $1 AND event_id = $2
        """, user_id, event_id)

        if bet:
            return {'option_index': bet['option_index'], 'amount': bet['amount']}
        return None

    async def place_bet(self, user_id: int, guild_id: int, event_id: int,
                        option_index: int, amount: int) -> Dict:
        """베팅 하기"""
        try:
            # 이벤트가 활성화되어 있는지 확인
            event = await self.bot.pool.fetchrow("""
                SELECT * FROM betting_events_v2 
                WHERE id = $1 AND guild_id = $2 AND status = 'active'
            """, event_id, guild_id)

            if not event:
                # 이벤트가 closed 상태인지 확인
                closed_event = await self.bot.pool.fetchrow("""
                    SELECT * FROM betting_events_v2 
                    WHERE id = $1 AND guild_id = $2 AND status = 'closed'
                """, event_id, guild_id)

                if closed_event:
                    return {'success': False, 'reason': '베팅이 마감되었습니다. 더 이상 새로운 베팅을 받지 않습니다.'}
                else:
                    return {'success': False, 'reason': '이벤트를 찾을 수 없거나 비활성 상태입니다'}

            if datetime.now(timezone.utc) > event['ends_at']:
                return {'success': False, 'reason': '베팅 시간이 만료되었습니다'}

            # 기존 베팅 확인
            existing_bet = await self.get_user_bet(user_id, event_id)
            if existing_bet:
                options = json.loads(event['options'])
                option_name = options[existing_bet['option_index']]
                return {
                    'success': False,
                    'reason': f'이미 **{option_name}**에 **{existing_bet["amount"]:,}** 코인을 베팅하셨습니다.\n한 이벤트당 하나의 옵션에만 베팅할 수 있습니다.'
                }

            # 코인 확인
            coins_cog = self.bot.get_cog('CoinsCog')
            if not coins_cog:
                return {'success': False, 'reason': '코인 시스템을 사용할 수 없습니다'}

            user_coins = await coins_cog.get_user_coins(user_id, guild_id)
            if user_coins < amount:
                return {'success': False, 'reason': f'코인이 부족합니다 (보유: {user_coins:,} 코인)'}

            # 카지노 자격 확인
            from cogs.coins import check_user_casino_eligibility
            eligibility = await check_user_casino_eligibility(self.bot, user_id, guild_id)
            if not eligibility['allowed']:
                return {'success': False, 'reason': eligibility['message']}

            # 코인 차감
            if not await coins_cog.remove_coins(user_id, guild_id, amount, "betting", f"베팅 - 이벤트 {event_id}"):
                return {'success': False, 'reason': '코인 차감에 실패했습니다'}

            # 베팅 기록
            await self.bot.pool.execute("""
                INSERT INTO betting_bets_v2 (event_id, user_id, guild_id, option_index, amount)
                VALUES ($1, $2, $3, $4, $5)
            """, event_id, user_id, guild_id, option_index, amount)

            # 베팅 디스플레이 업데이트
            await self.update_betting_display(event_id)

            options = json.loads(event['options'])
            return {
                'success': True,
                'option_name': options[option_index],
                'remaining_coins': await coins_cog.get_user_coins(user_id, guild_id)
            }

        except Exception as e:
            self.logger.error(f"베팅 실패: {e}")
            return {'success': False, 'reason': '내부 오류가 발생했습니다'}

    async def update_betting_display(self, event_id: int):
        """베팅 디스플레이 업데이트"""
        try:
            # 이벤트 가져오기
            event = await self.bot.pool.fetchrow("""
                SELECT * FROM betting_events_v2 WHERE id = $1
            """, event_id)

            if not event or not event['message_id']:
                return

            # 채널과 메시지 가져오기
            channel = self.bot.get_channel(event['channel_id'])
            if not channel:
                return

            try:
                message = await channel.fetch_message(event['message_id'])
            except discord.NotFound:
                return

            options = json.loads(event['options'])

            # 업데이트된 임베드 생성
            embed = await self.create_betting_embed(event_id, options, event)

            # 메시지 업데이트
            await message.edit(embed=embed)

        except Exception as e:
            self.logger.error(f"베팅 디스플레이 업데이트 실패: {e}")

    async def close_betting(self, event_id: int) -> Dict:
        """베팅을 마감하여 새로운 베팅을 받지 않음"""
        try:
            # 이벤트 상태를 'closed'로 변경
            result = await self.bot.pool.execute("""
                UPDATE betting_events_v2 
                SET status = 'closed' 
                WHERE id = $1 AND status = 'active'
            """, event_id)

            if result == "UPDATE 0":
                return {'success': False, 'reason': '활성화된 이벤트를 찾을 수 없습니다'}

            # 디스플레이 업데이트
            await self.update_betting_display(event_id)

            return {'success': True}

        except Exception as e:
            self.logger.error(f"베팅 마감 실패: {e}")
            return {'success': False, 'reason': str(e)}

    async def end_betting(self, event_id: int, winner_index: int) -> Dict:
        """베팅 종료 및 상금 분배"""
        try:
            # 이벤트 가져오기
            event = await self.bot.pool.fetchrow("""
                SELECT * FROM betting_events_v2 WHERE id = $1
            """, event_id)

            if not event:
                return {'success': False, 'reason': '이벤트를 찾을 수 없습니다'}

            if event['status'] not in ['active', 'closed']:
                return {'success': False, 'reason': '이미 종료된 이벤트입니다'}

            # 이벤트 상태 업데이트
            await self.bot.pool.execute("""
                UPDATE betting_events_v2 
                SET status = 'ended', winner_option = $1 
                WHERE id = $2
            """, winner_index, event_id)

            # 모든 베팅 가져오기
            all_bets = await self.bot.pool.fetch("""
                SELECT * FROM betting_bets_v2 WHERE event_id = $1
            """, event_id)

            # 배당금 계산
            total_pool = sum(bet['amount'] for bet in all_bets)
            winning_bets = [bet for bet in all_bets if bet['option_index'] == winner_index]
            winning_pool = sum(bet['amount'] for bet in winning_bets)

            if winning_pool > 0 and total_pool > 0:
                coins_cog = self.bot.get_cog('CoinsCog')
                if coins_cog:
                    for bet in winning_bets:
                        # 배당금 계산 (전체 풀에서 비례 분배)
                        payout = int((bet['amount'] / winning_pool) * total_pool)

                        # 배당금 지급
                        await coins_cog.add_coins(
                            bet['user_id'],
                            bet['guild_id'],
                            payout,
                            "betting_win",
                            f"베팅 승리: {event['title']}"
                        )

                        # 베팅 기록 업데이트
                        await self.bot.pool.execute("""
                            UPDATE betting_bets_v2 SET payout = $1 WHERE id = $2
                        """, payout, bet['id'])

            # 최종 디스플레이 업데이트
            await self.update_final_display(event_id, winner_index)

            # 10분 후 채널 삭제 스케줄
            channel_id = event['channel_id']
            if channel_id:
                asyncio.create_task(self.schedule_channel_deletion(channel_id, event_id))

            return {
                'success': True,
                'winners': len(winning_bets),
                'total_payout': total_pool,
                'winner_option': json.loads(event['options'])[winner_index]
            }

        except Exception as e:
            self.logger.error(f"베팅 종료 실패: {e}")
            return {'success': False, 'reason': str(e)}

    async def schedule_channel_deletion(self, channel_id: int, event_id: int):
        """10분 후 채널 삭제 스케줄"""
        try:
            # 10분 대기
            await asyncio.sleep(600)  # 600초 = 10분

            channel = self.bot.get_channel(channel_id)
            if channel:
                try:
                    await channel.delete(reason=f"베팅 이벤트 {event_id} 종료 후 자동 삭제")
                    self.logger.info(f"베팅 채널 {channel_id} 자동 삭제 완료")
                except discord.HTTPException as e:
                    self.logger.error(f"채널 삭제 실패: {e}")

        except Exception as e:
            self.logger.error(f"채널 삭제 스케줄 오류: {e}")

    async def update_final_display(self, event_id: int, winner_index: int):
        """최종 결과로 디스플레이 업데이트"""
        try:
            event = await self.bot.pool.fetchrow("""
                SELECT * FROM betting_events_v2 WHERE id = $1
            """, event_id)

            if not event or not event['message_id']:
                return

            channel = self.bot.get_channel(event['channel_id'])
            if not channel:
                return

            try:
                message = await channel.fetch_message(event['message_id'])
            except discord.NotFound:
                return

            options = json.loads(event['options'])
            winner_option = options[winner_index]

            # 최종 임베드 생성
            embed = discord.Embed(
                title=f"🏆 {event['title']} - 종료",
                description=f"**승리 옵션: {winner_option}**",
                color=discord.Color.green()
            )

            # 최종 통계 가져오기
            stats = await self.bot.pool.fetch("""
                SELECT option_index, COUNT(*) as bets, SUM(amount) as total, SUM(payout) as payouts
                FROM betting_bets_v2 
                WHERE event_id = $1
                GROUP BY option_index
                ORDER BY option_index
            """, event_id)

            option_text = ""
            total_amount = sum(stat['total'] or 0 for stat in stats)

            for i, option in enumerate(options):
                option_stats = next((s for s in stats if s['option_index'] == i), None)
                bets = option_stats['bets'] if option_stats else 0
                amount = option_stats['total'] if option_stats else 0
                payouts = option_stats['payouts'] if option_stats else 0

                status = "🏆" if i == winner_index else "❌"
                percentage = (amount / total_amount * 100) if total_amount > 0 else 0

                option_text += f"{status} **{option}**\n"
                option_text += f"💰 {amount:,} 코인 ({bets}명) - {percentage:.1f}%\n"
                if i == winner_index and payouts > 0:
                    option_text += f"💸 배당금: {payouts:,} 코인\n"
                option_text += "\n"

            embed.add_field(name="🎯 최종 결과", value=option_text, inline=False)

            # 뷰 제거 및 메시지 업데이트
            await message.edit(embed=embed, view=None)

            # 최종 발표
            await channel.send(f"🎉 베팅 종료! 승리 옵션: **{winner_option}** 🎉")

        except Exception as e:
            self.logger.error(f"최종 디스플레이 업데이트 실패: {e}")

    @tasks.loop(minutes=1)
    async def cleanup_task(self):
        """만료된 이벤트를 자동으로 마감합니다."""
        try:
            # Find active events where the end time has passed.
            expired_events = await self.bot.pool.fetch("""
                    SELECT id FROM betting_events_v2
                    WHERE status = 'active' AND ends_at < NOW()
                """)

            for event in expired_events:
                event_id = event['id']
                self.logger.info(f"Event ID {event_id} has expired. Automatically closing betting.")
                # Call the close_betting function to handle closing and display updates.
                await self.close_betting(event_id)

        except Exception as e:
            self.logger.error(f"An error occurred in the betting cleanup task: {e}")

    # 슬래시 명령어들
    @app_commands.command(name="베팅마감", description="베팅을 마감하여 새로운 베팅을 받지 않습니다 (관리자 전용)")
    @app_commands.describe(event_id="마감할 이벤트 ID")
    async def close_bet_command(self, interaction: discord.Interaction, event_id: int):
        if not self.has_admin_permissions(interaction.user):
            await interaction.response.send_message("관리자 권한이 필요합니다", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        result = await self.close_betting(event_id)

        if result['success']:
            await interaction.followup.send(
                f"✅ 베팅이 마감되었습니다! (이벤트 ID: {event_id})\n"
                f"더 이상 새로운 베팅을 받지 않습니다. `/베팅종료` 명령어로 결과를 발표하세요.",
                ephemeral=True
            )
        else:
            await interaction.followup.send(f"❌ 실패: {result['reason']}", ephemeral=True)

    @app_commands.command(name="베팅종료", description="베팅 이벤트를 종료합니다 (관리자 전용)")
    @app_commands.describe(
        event_id="종료할 이벤트 ID",
        winner_option="승리한 옵션 번호 (1부터 시작)"
    )
    async def end_bet_command(self, interaction: discord.Interaction,
                              event_id: int, winner_option: int):
        if not self.has_admin_permissions(interaction.user):
            await interaction.response.send_message("관리자 권한이 필요합니다", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # 이벤트 확인하여 승리 옵션 검증
        event = await self.bot.pool.fetchrow("""
            SELECT options FROM betting_events_v2 WHERE id = $1 AND guild_id = $2
        """, event_id, interaction.guild.id)

        if not event:
            await interaction.followup.send("이벤트를 찾을 수 없습니다", ephemeral=True)
            return

        options = json.loads(event['options'])
        if winner_option < 1 or winner_option > len(options):
            await interaction.followup.send(f"잘못된 옵션입니다. 1-{len(options)} 사이의 숫자를 입력하세요", ephemeral=True)
            return

        result = await self.end_betting(event_id, winner_option - 1)

        if result['success']:
            await interaction.followup.send(
                f"✅ 베팅이 종료되었습니다!\n"
                f"승리 옵션: **{result['winner_option']}**\n"
                f"승리자: {result['winners']}명\n"
                f"총 배당금: {result['total_payout']:,} 코인\n"
                f"📝 채널은 10분 후 자동으로 삭제됩니다.",
                ephemeral=True
            )
        else:
            await interaction.followup.send(f"❌ 실패: {result['reason']}", ephemeral=True)

    @app_commands.command(name="베팅목록", description="활성화된 베팅 이벤트 목록을 확인합니다")
    async def list_bets(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        events = await self.bot.pool.fetch("""
            SELECT id, title, status, ends_at, channel_id 
            FROM betting_events_v2 
            WHERE guild_id = $1 AND status IN ('active', 'closed', 'expired')
            ORDER BY created_at DESC
            LIMIT 10
        """, interaction.guild.id)

        if not events:
            await interaction.followup.send("활성화된 베팅 이벤트가 없습니다", ephemeral=True)
            return

        embed = discord.Embed(title="베팅 이벤트 목록", color=discord.Color.blue())

        for event in events:
            if event['status'] == 'active':
                status = "🟢 진행중"
            elif event['status'] == 'closed':
                status = "🟡 마감됨"
            else:
                status = "🔴 만료됨"

            embed.add_field(
                name=f"ID {event['id']}: {event['title']}",
                value=f"{status}\n종료: <t:{int(event['ends_at'].timestamp())}:R>\n<#{event['channel_id']}>",
                inline=False
            )

        embed.set_footer(text="마감된 이벤트는 /베팅종료로 결과를 발표할 수 있습니다")
        await interaction.followup.send(embed=embed, ephemeral=True)


# 뷰 클래스들
class CreateBettingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="베팅 이벤트 생성", style=discord.ButtonStyle.green, emoji="🎲")
    async def create_betting(self, interaction: discord.Interaction, button: discord.ui.Button):
        betting_cog = interaction.client.get_cog('SimpleBettingCog')
        if not betting_cog or not betting_cog.has_admin_permissions(interaction.user):
            await interaction.response.send_message("관리자 권한이 필요합니다", ephemeral=True)
            return

        modal = CreateBettingModal()
        await interaction.response.send_modal(modal)


class CreateBettingModal(discord.ui.Modal, title="베팅 이벤트 생성"):
    def __init__(self):
        super().__init__()

    title_input = discord.ui.TextInput(
        label="이벤트 제목",
        placeholder="베팅 이벤트 제목을 입력하세요",
        required=True,
        max_length=100
    )

    options_input = discord.ui.TextInput(
        label="옵션 (한 줄에 하나씩)",
        placeholder="옵션 1\n옵션 2\n옵션 3",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=500
    )

    end_time_input = discord.ui.TextInput(
        label="종료 시간 (Eastern 시간대, 예: 14:30, 23:45)",
        placeholder="14:30",
        required=True,
        max_length=10
    )

    end_date_input = discord.ui.TextInput(
        label="종료 날짜 (Eastern, 선택사항, 예: 2024-12-25)",
        placeholder="오늘 날짜로 설정하려면 비워두세요 (Eastern 기준)",
        required=False,
        max_length=15
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            # Import timezone support for Eastern Time
            from zoneinfo import ZoneInfo

            # Parse the end time
            time_str = self.end_time_input.value.strip()
            if ':' not in time_str:
                await interaction.followup.send("시간 형식이 올바르지 않습니다. HH:MM 형식으로 입력하세요 (예: 14:30)", ephemeral=True)
                return

            try:
                hour, minute = map(int, time_str.split(':'))
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError
            except ValueError:
                await interaction.followup.send("올바른 시간을 입력하세요 (00:00 - 23:59)", ephemeral=True)
                return

            # Get current time in Eastern timezone
            eastern_tz = ZoneInfo("America/New_York")
            now_eastern = datetime.now(eastern_tz)
            now_utc = datetime.now(timezone.utc)

            # Parse the end date (if provided)
            if self.end_date_input.value.strip():
                date_str = self.end_date_input.value.strip()
                try:
                    # Parse date in YYYY-MM-DD format
                    year, month, day = map(int, date_str.split('-'))
                    # Create datetime in Eastern timezone
                    target_date_eastern = datetime(year, month, day, hour, minute, tzinfo=eastern_tz)
                except ValueError:
                    await interaction.followup.send("날짜 형식이 올바르지 않습니다. YYYY-MM-DD 형식으로 입력하세요 (예: 2024-12-25)",
                                                    ephemeral=True)
                    return
            else:
                # Use today's date in Eastern timezone
                target_date_eastern = datetime(now_eastern.year, now_eastern.month, now_eastern.day,
                                               hour, minute, tzinfo=eastern_tz)

                # If the time has already passed today, set it for tomorrow
                if target_date_eastern <= now_eastern:
                    target_date_eastern += timedelta(days=1)

            # Convert Eastern time to UTC for storage
            target_date_utc = target_date_eastern.astimezone(timezone.utc)

            # Validate that the end time is in the future
            if target_date_utc <= now_utc:
                await interaction.followup.send("종료 시간은 현재 시간보다 미래여야 합니다", ephemeral=True)
                return

            # Validate maximum duration (e.g., max 7 days)
            max_duration = timedelta(days=7)
            if target_date_utc - now_utc > max_duration:
                await interaction.followup.send("베팅 이벤트는 최대 7일까지만 설정할 수 있습니다", ephemeral=True)
                return

            # Validate minimum duration (e.g., at least 5 minutes)
            min_duration = timedelta(minutes=5)
            if target_date_utc - now_utc < min_duration:
                await interaction.followup.send("베팅 이벤트는 최소 5분 후에 종료되도록 설정해야 합니다", ephemeral=True)
                return

            # Parse options
            options = [opt.strip() for opt in self.options_input.value.split('\n') if opt.strip()]
            if len(options) < 2 or len(options) > 8:
                await interaction.followup.send("2-8개의 옵션이 필요합니다", ephemeral=True)
                return

            # Create the betting event with the specific end time (in UTC)
            betting_cog = interaction.client.get_cog('SimpleBettingCog')
            result = await betting_cog.create_betting_event_with_end_time(
                interaction.guild.id,
                self.title_input.value,
                options,
                interaction.user.id,
                target_date_utc
            )

            if result['success']:
                # Show current Eastern time for reference
                current_eastern = now_eastern.strftime("%Y-%m-%d %H:%M EST/EDT")
                target_eastern_display = target_date_eastern.strftime("%Y-%m-%d %H:%M EST/EDT")

                await interaction.followup.send(
                    f"✅ 베팅 이벤트가 생성되었습니다!\n"
                    f"채널: <#{result['channel_id']}>\n"
                    f"종료: <t:{int(result['ends_at'].timestamp())}:F> (<t:{int(result['ends_at'].timestamp())}:R>)\n"
                    f"🕐 현재 Eastern 시간: {current_eastern}\n"
                    f"📅 설정된 종료 시간 (Eastern): {target_eastern_display}\n\n"
                    f"🔧 **관리자 제어**\n"
                    f"베팅 마감: `/베팅마감 event_id:{result['event_id']}`\n"
                    f"베팅 종료: `/베팅종료 event_id:{result['event_id']} winner_option:[1-8]`",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(f"❌ 실패: {result['reason']}", ephemeral=True)

        except ImportError:
            await interaction.followup.send("시간대 처리 모듈을 찾을 수 없습니다. 시스템 관리자에게 문의하세요.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"오류: {e}", ephemeral=True)

class BettingEventView(discord.ui.View):
    def __init__(self, event_id: int, options: List[str]):
        super().__init__(timeout=None)
        self.event_id = event_id
        self.options = options

    @discord.ui.button(label="1", style=discord.ButtonStyle.primary, emoji="💰", custom_id="bet_0")
    async def bet_option_0(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_bet_option(interaction, 0)

    @discord.ui.button(label="2", style=discord.ButtonStyle.secondary, emoji="💰", custom_id="bet_1")
    async def bet_option_1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_bet_option(interaction, 1)

    @discord.ui.button(label="3", style=discord.ButtonStyle.success, emoji="💰", custom_id="bet_2")
    async def bet_option_2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_bet_option(interaction, 2)

    @discord.ui.button(label="4", style=discord.ButtonStyle.danger, emoji="💰", custom_id="bet_3")
    async def bet_option_3(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_bet_option(interaction, 3)

    @discord.ui.button(label="5", style=discord.ButtonStyle.primary, emoji="💰", custom_id="bet_4", row=1)
    async def bet_option_4(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_bet_option(interaction, 4)

    @discord.ui.button(label="6", style=discord.ButtonStyle.secondary, emoji="💰", custom_id="bet_5", row=1)
    async def bet_option_5(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_bet_option(interaction, 5)

    @discord.ui.button(label="7", style=discord.ButtonStyle.success, emoji="💰", custom_id="bet_6", row=1)
    async def bet_option_6(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_bet_option(interaction, 6)

    @discord.ui.button(label="8", style=discord.ButtonStyle.danger, emoji="💰", custom_id="bet_7", row=1)
    async def bet_option_7(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_bet_option(interaction, 7)

    async def handle_bet_option(self, interaction: discord.Interaction, option_index: int):
        """베팅 옵션 버튼 클릭 처리"""
        try:
            betting_cog = interaction.client.get_cog('SimpleBettingCog')
            if not betting_cog:
                await interaction.response.send_message("베팅 시스템을 사용할 수 없습니다", ephemeral=True)
                return

            # 옵션이 유효한지 확인
            if option_index >= len(self.options):
                await interaction.response.send_message("유효하지 않은 옵션입니다", ephemeral=True)
                return

            # 기존 베팅 확인
            existing_bet = await betting_cog.get_user_bet(interaction.user.id, self.event_id)
            if existing_bet:
                option_name = self.options[existing_bet['option_index']]
                await interaction.response.send_message(
                    f"❌ 이미 **{option_name}**에 **{existing_bet['amount']:,}** 코인을 베팅하셨습니다.\n"
                    f"한 이벤트당 하나의 옵션에만 베팅할 수 있습니다.",
                    ephemeral=True
                )
                return

            # 베팅 모달 표시
            modal = BetAmountModal(self.event_id, option_index, self.options[option_index])
            await interaction.response.send_modal(modal)

        except Exception as e:
            betting_cog.logger.error(f"베팅 옵션 처리 오류: {e}")
            await interaction.response.send_message("오류가 발생했습니다", ephemeral=True)


class BetAmountModal(discord.ui.Modal):
    def __init__(self, event_id: int, option_index: int, option_name: str):
        super().__init__(title=f"베팅하기: {option_name}")
        self.event_id = event_id
        self.option_index = option_index
        self.option_name = option_name

    amount_input = discord.ui.TextInput(
        label="베팅할 코인 수량",
        placeholder="베팅할 코인을 입력하세요 (최소 10 코인)",
        required=True,
        max_length=10
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            amount = int(self.amount_input.value.replace(',', ''))

            if amount < 10:
                await interaction.followup.send("최소 베팅 금액은 10 코인입니다", ephemeral=True)
                return

            if amount > 1000000:  # 최대 베팅 제한
                await interaction.followup.send("최대 베팅 금액은 1,000,000 코인입니다", ephemeral=True)
                return

            betting_cog = interaction.client.get_cog('SimpleBettingCog')
            result = await betting_cog.place_bet(
                interaction.user.id,
                interaction.guild.id,
                self.event_id,
                self.option_index,
                amount
            )

            if result['success']:
                embed = discord.Embed(
                    title="✅ 베팅 성공!",
                    color=discord.Color.green()
                )
                embed.add_field(
                    name="베팅 정보",
                    value=f"**옵션**: {result['option_name']}\n"
                          f"**금액**: {amount:,} 코인\n"
                          f"**잔여 코인**: {result['remaining_coins']:,} 코인",
                    inline=False
                )
                embed.set_footer(text="베팅이 완료되었습니다. 결과를 기다려주세요!")

                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send(f"❌ {result['reason']}", ephemeral=True)

        except ValueError:
            await interaction.followup.send("올바른 숫자를 입력해주세요", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"오류: {e}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(SimpleBettingCog(bot))