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

# Constants
BETTING_CONTROL_CHANNEL_ID = 1419346557232484352
BETTING_CATEGORY_ID = 1417712502220783716


class SimpleBettingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("SimpleBetting")
        self.logger.info("Simplified betting system initializing...")

        # Start initialization task
        self.bot.loop.create_task(self.initialize())

    async def initialize(self):
        """Initialize the betting system"""
        await self.bot.wait_until_ready()
        await self.setup_database()
        self.cleanup_task.start()
        await self.setup_control_panel()
        self.logger.info("Simplified betting system ready!")

    async def setup_database(self):
        """Create database tables"""
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

            self.logger.info("Database setup complete")
        except Exception as e:
            self.logger.error(f"Database setup failed: {e}")

    async def setup_control_panel(self):
        """Setup control panel with simple button"""
        try:
            channel = self.bot.get_channel(BETTING_CONTROL_CHANNEL_ID)
            if not channel:
                return

            # Clean up old messages
            async for message in channel.history(limit=10):
                if message.author == self.bot.user:
                    try:
                        await message.delete()
                    except:
                        pass

            embed = discord.Embed(
                title="🎲 Betting Control Panel",
                description="Click the button below to create a new betting event.",
                color=discord.Color.gold()
            )

            view = CreateBettingView()
            message = await channel.send(embed=embed, view=view)
            self.bot.add_view(view, message_id=message.id)

            self.logger.info("Control panel setup complete")
        except Exception as e:
            self.logger.error(f"Control panel setup failed: {e}")

    def has_admin_permissions(self, member: discord.Member) -> bool:
        """Check admin permissions"""
        return member.guild_permissions.administrator

    async def create_betting_event(self, guild_id: int, title: str, options: List[str],
                                   creator_id: int, duration_minutes: int) -> Dict:
        """Create a new betting event"""
        try:
            # Create channel
            guild = self.bot.get_guild(guild_id)
            category = guild.get_channel(BETTING_CATEGORY_ID)

            channel_name = f"betting-{title.replace(' ', '-')[:20]}"
            betting_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                topic=f"Betting: {title}"
            )

            # Set permissions
            await betting_channel.set_permissions(
                guild.default_role,
                send_messages=False,
                add_reactions=False
            )

            # Calculate end time
            ends_at = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)

            # Insert into database
            event_id = await self.bot.pool.fetchval("""
                INSERT INTO betting_events_v2 
                (guild_id, title, options, creator_id, ends_at, channel_id)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
            """, guild_id, title, json.dumps(options), creator_id, ends_at, betting_channel.id)

            # Create betting message
            await self.create_betting_message(event_id, betting_channel)

            return {
                'success': True,
                'event_id': event_id,
                'channel_id': betting_channel.id,
                'ends_at': ends_at
            }

        except Exception as e:
            self.logger.error(f"Failed to create betting event: {e}")
            return {'success': False, 'reason': str(e)}

    async def create_betting_message(self, event_id: int, channel: discord.TextChannel):
        """Create the betting message in channel"""
        try:
            # Get event data
            event = await self.bot.pool.fetchrow("""
                SELECT * FROM betting_events_v2 WHERE id = $1
            """, event_id)

            if not event:
                return

            options = json.loads(event['options'])

            # Create embed
            embed = discord.Embed(
                title=f"🎲 {event['title']}",
                description="Choose your option and place your bet!",
                color=discord.Color.gold()
            )

            # Add options
            option_text = ""
            for i, option in enumerate(options):
                option_text += f"{i + 1}. **{option}**\n"

            embed.add_field(name="Options", value=option_text, inline=False)
            embed.add_field(name="Ends", value=f"<t:{int(event['ends_at'].timestamp())}:R>", inline=True)

            # Create view with simple buttons
            view = BettingEventView(event_id)
            message = await channel.send(embed=embed, view=view)

            # Update database with message ID
            await self.bot.pool.execute("""
                UPDATE betting_events_v2 SET message_id = $1 WHERE id = $2
            """, message.id, event_id)

            # Register view
            self.bot.add_view(view, message_id=message.id)

            self.logger.info(f"Created betting message for event {event_id}")

        except Exception as e:
            self.logger.error(f"Failed to create betting message: {e}")

    async def place_bet(self, user_id: int, guild_id: int, event_id: int,
                        option_index: int, amount: int) -> Dict:
        """Place a bet"""
        try:
            # Check if event is active
            event = await self.bot.pool.fetchrow("""
                SELECT * FROM betting_events_v2 
                WHERE id = $1 AND guild_id = $2 AND status = 'active'
            """, event_id, guild_id)

            if not event:
                return {'success': False, 'reason': 'Event not found or not active'}

            if datetime.now(timezone.utc) > event['ends_at']:
                return {'success': False, 'reason': 'Betting has ended'}

            # Check coins
            coins_cog = self.bot.get_cog('CoinsCog')
            if not coins_cog:
                return {'success': False, 'reason': 'Coins system not available'}

            user_coins = await coins_cog.get_user_coins(user_id, guild_id)
            if user_coins < amount:
                return {'success': False, 'reason': f'Insufficient coins (You have: {user_coins:,})'}

            # Remove coins
            if not await coins_cog.remove_coins(user_id, guild_id, amount, "betting", f"Bet on event {event_id}"):
                return {'success': False, 'reason': 'Failed to remove coins'}

            # Record bet
            await self.bot.pool.execute("""
                INSERT INTO betting_bets_v2 (event_id, user_id, guild_id, option_index, amount)
                VALUES ($1, $2, $3, $4, $5)
            """, event_id, user_id, guild_id, option_index, amount)

            # Update betting display
            await self.update_betting_display(event_id)

            return {
                'success': True,
                'remaining_coins': await coins_cog.get_user_coins(user_id, guild_id)
            }

        except Exception as e:
            self.logger.error(f"Failed to place bet: {e}")
            return {'success': False, 'reason': 'Internal error'}

    async def update_betting_display(self, event_id: int):
        """Update the betting display"""
        try:
            # Get event and stats
            event = await self.bot.pool.fetchrow("""
                SELECT * FROM betting_events_v2 WHERE id = $1
            """, event_id)

            if not event or not event['message_id']:
                return

            # Get betting stats
            stats = await self.bot.pool.fetch("""
                SELECT option_index, COUNT(*) as bets, SUM(amount) as total
                FROM betting_bets_v2 
                WHERE event_id = $1
                GROUP BY option_index
                ORDER BY option_index
            """, event_id)

            # Get channel and message
            channel = self.bot.get_channel(event['channel_id'])
            if not channel:
                return

            try:
                message = await channel.fetch_message(event['message_id'])
            except discord.NotFound:
                return

            options = json.loads(event['options'])

            # Create updated embed
            embed = discord.Embed(
                title=f"🎲 {event['title']}",
                description="Choose your option and place your bet!",
                color=discord.Color.gold()
            )

            # Add options with stats
            option_text = ""
            total_amount = sum(stat['total'] or 0 for stat in stats)

            for i, option in enumerate(options):
                # Find stats for this option
                option_stats = next((s for s in stats if s['option_index'] == i), None)
                bets = option_stats['bets'] if option_stats else 0
                amount = option_stats['total'] if option_stats else 0

                percentage = (amount / total_amount * 100) if total_amount > 0 else 0

                option_text += f"{i + 1}. **{option}**\n"
                option_text += f"   💰 {amount:,} coins ({bets} bets) - {percentage:.1f}%\n"

            embed.add_field(name="Options", value=option_text, inline=False)
            embed.add_field(name="Total Pool", value=f"{total_amount:,} coins", inline=True)
            embed.add_field(name="Ends", value=f"<t:{int(event['ends_at'].timestamp())}:R>", inline=True)

            # Update message
            await message.edit(embed=embed)

        except Exception as e:
            self.logger.error(f"Failed to update betting display: {e}")

    async def end_betting(self, event_id: int, winner_index: int) -> Dict:
        """End betting and distribute winnings"""
        try:
            # Get event
            event = await self.bot.pool.fetchrow("""
                SELECT * FROM betting_events_v2 WHERE id = $1
            """, event_id)

            if not event:
                return {'success': False, 'reason': 'Event not found'}

            # Update event status
            await self.bot.pool.execute("""
                UPDATE betting_events_v2 
                SET status = 'ended', winner_option = $1 
                WHERE id = $2
            """, winner_index, event_id)

            # Get all bets
            all_bets = await self.bot.pool.fetch("""
                SELECT * FROM betting_bets_v2 WHERE event_id = $1
            """, event_id)

            # Calculate payouts
            total_pool = sum(bet['amount'] for bet in all_bets)
            winning_bets = [bet for bet in all_bets if bet['option_index'] == winner_index]
            winning_pool = sum(bet['amount'] for bet in winning_bets)

            if winning_pool > 0:
                coins_cog = self.bot.get_cog('CoinsCog')
                if coins_cog:
                    for bet in winning_bets:
                        # Calculate payout (proportional share of total pool)
                        payout = int((bet['amount'] / winning_pool) * total_pool)

                        # Give payout
                        await coins_cog.add_coins(
                            bet['user_id'],
                            bet['guild_id'],
                            payout,
                            "betting_win",
                            f"Won betting event: {event['title']}"
                        )

                        # Update bet record
                        await self.bot.pool.execute("""
                            UPDATE betting_bets_v2 SET payout = $1 WHERE id = $2
                        """, payout, bet['id'])

            # Update final display
            await self.update_final_display(event_id, winner_index)

            return {'success': True, 'winners': len(winning_bets), 'total_payout': total_pool}

        except Exception as e:
            self.logger.error(f"Failed to end betting: {e}")
            return {'success': False, 'reason': str(e)}

    async def update_final_display(self, event_id: int, winner_index: int):
        """Update display with final results"""
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

            # Create final embed
            embed = discord.Embed(
                title=f"🏆 {event['title']} - ENDED",
                description=f"**Winner: {winner_option}**",
                color=discord.Color.green()
            )

            # Get final stats
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
                option_text += f"{status} **{option}**\n"
                option_text += f"   💰 {amount:,} coins ({bets} bets)\n"
                if i == winner_index and payouts > 0:
                    option_text += f"   💸 Paid out: {payouts:,} coins\n"

            embed.add_field(name="Final Results", value=option_text, inline=False)

            # Remove view and update message
            await message.edit(embed=embed, view=None)

            # Send final announcement
            await channel.send(f"🎉 Betting ended! Winner: **{winner_option}** 🎉")

        except Exception as e:
            self.logger.error(f"Failed to update final display: {e}")

    @tasks.loop(minutes=1)
    async def cleanup_task(self):
        """Clean up expired events"""
        try:
            expired = await self.bot.pool.fetch("""
                SELECT id FROM betting_events_v2 
                WHERE status = 'active' AND ends_at < NOW()
            """)

            for event in expired:
                await self.bot.pool.execute("""
                    UPDATE betting_events_v2 SET status = 'expired' WHERE id = $1
                """, event['id'])

        except Exception as e:
            self.logger.error(f"Cleanup task error: {e}")

    # Slash Commands
    @app_commands.command(name="endbet", description="End a betting event (Admin only)")
    async def end_bet_command(self, interaction: discord.Interaction,
                              event_id: int, winner_option: int):
        if not self.has_admin_permissions(interaction.user):
            await interaction.response.send_message("No permission", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # Get event to validate winner option
        event = await self.bot.pool.fetchrow("""
            SELECT options FROM betting_events_v2 WHERE id = $1 AND guild_id = $2
        """, event_id, interaction.guild.id)

        if not event:
            await interaction.followup.send("Event not found", ephemeral=True)
            return

        options = json.loads(event['options'])
        if winner_option < 1 or winner_option > len(options):
            await interaction.followup.send(f"Invalid option. Must be 1-{len(options)}", ephemeral=True)
            return

        result = await self.end_betting(event_id, winner_option - 1)

        if result['success']:
            await interaction.followup.send(
                f"✅ Betting ended! {result['winners']} winners, {result['total_payout']:,} coins distributed",
                ephemeral=True
            )
        else:
            await interaction.followup.send(f"❌ Failed: {result['reason']}", ephemeral=True)

    @app_commands.command(name="listbets", description="List active betting events")
    async def list_bets(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        events = await self.bot.pool.fetch("""
            SELECT id, title, status, ends_at, channel_id 
            FROM betting_events_v2 
            WHERE guild_id = $1 AND status IN ('active', 'expired')
            ORDER BY created_at DESC
            LIMIT 10
        """, interaction.guild.id)

        if not events:
            await interaction.followup.send("No active betting events", ephemeral=True)
            return

        embed = discord.Embed(title="Active Betting Events", color=discord.Color.blue())

        for event in events:
            status = "🟢 Active" if event['status'] == 'active' else "🟡 Expired"
            embed.add_field(
                name=f"ID {event['id']}: {event['title']}",
                value=f"{status}\nEnds: <t:{int(event['ends_at'].timestamp())}:R>\n<#{event['channel_id']}>",
                inline=False
            )

        await interaction.followup.send(embed=embed, ephemeral=True)


# Simple Views
class CreateBettingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Create Betting Event", style=discord.ButtonStyle.green, emoji="🎲")
    async def create_betting(self, interaction: discord.Interaction, button: discord.ui.Button):
        betting_cog = interaction.client.get_cog('SimpleBettingCog')
        if not betting_cog or not betting_cog.has_admin_permissions(interaction.user):
            await interaction.response.send_message("No permission", ephemeral=True)
            return

        modal = CreateBettingModal()
        await interaction.response.send_modal(modal)


class CreateBettingModal(discord.ui.Modal, title="Create Betting Event"):
    def __init__(self):
        super().__init__()

    title_input = discord.ui.TextInput(
        label="Event Title",
        placeholder="Enter betting event title",
        required=True,
        max_length=100
    )

    options_input = discord.ui.TextInput(
        label="Options (one per line)",
        placeholder="Option 1\nOption 2\nOption 3",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=500
    )

    duration_input = discord.ui.TextInput(
        label="Duration (minutes)",
        placeholder="30",
        required=True,
        max_length=10
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            duration = int(self.duration_input.value)
            if duration < 1 or duration > 1440:  # Max 24 hours
                await interaction.followup.send("Duration must be 1-1440 minutes", ephemeral=True)
                return

            options = [opt.strip() for opt in self.options_input.value.split('\n') if opt.strip()]
            if len(options) < 2 or len(options) > 8:
                await interaction.followup.send("Must have 2-8 options", ephemeral=True)
                return

            betting_cog = interaction.client.get_cog('SimpleBettingCog')
            result = await betting_cog.create_betting_event(
                interaction.guild.id,
                self.title_input.value,
                options,
                interaction.user.id,
                duration
            )

            if result['success']:
                await interaction.followup.send(
                    f"✅ Created betting event!\nChannel: <#{result['channel_id']}>\n"
                    f"Ends: <t:{int(result['ends_at'].timestamp())}:R>",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(f"❌ Failed: {result['reason']}", ephemeral=True)

        except ValueError:
            await interaction.followup.send("Invalid duration", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)


class BettingEventView(discord.ui.View):
    def __init__(self, event_id: int):
        super().__init__(timeout=None)
        self.event_id = event_id

    @discord.ui.button(label="Place Bet", style=discord.ButtonStyle.primary, emoji="💰")
    async def place_bet_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Get event to show options
        betting_cog = interaction.client.get_cog('SimpleBettingCog')
        event = await betting_cog.bot.pool.fetchrow("""
            SELECT options FROM betting_events_v2 WHERE id = $1
        """, self.event_id)

        if not event:
            await interaction.response.send_message("Event not found", ephemeral=True)
            return

        modal = PlaceBetModal(self.event_id, json.loads(event['options']))
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="My Bets", style=discord.ButtonStyle.secondary, emoji="📊")
    async def my_bets_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        betting_cog = interaction.client.get_cog('SimpleBettingCog')
        bets = await betting_cog.bot.pool.fetch("""
            SELECT option_index, amount, payout, placed_at 
            FROM betting_bets_v2 
            WHERE event_id = $1 AND user_id = $2
        """, self.event_id, interaction.user.id)

        if not bets:
            await interaction.followup.send("You have no bets on this event", ephemeral=True)
            return

        # Get event info
        event = await betting_cog.bot.pool.fetchrow("""
            SELECT title, options FROM betting_events_v2 WHERE id = $1
        """, self.event_id)

        options = json.loads(event['options'])
        embed = discord.Embed(
            title=f"Your Bets: {event['title']}",
            color=discord.Color.blue()
        )

        total_bet = sum(bet['amount'] for bet in bets)
        total_payout = sum(bet['payout'] for bet in bets)

        for bet in bets:
            option_name = options[bet['option_index']]
            status = "🏆 Won" if bet['payout'] > 0 else "⏳ Pending" if bet['payout'] == 0 else "❌ Lost"

            embed.add_field(
                name=f"{option_name}",
                value=f"Bet: {bet['amount']:,} coins\nStatus: {status}\n"
                      f"Payout: {bet['payout']:,} coins" if bet[
                                                                'payout'] > 0 else f"Bet: {bet['amount']:,} coins\nStatus: {status}",
                inline=True
            )

        embed.add_field(
            name="Summary",
            value=f"Total bet: {total_bet:,} coins\nTotal payout: {total_payout:,} coins\n"
                  f"Net: {total_payout - total_bet:,} coins",
            inline=False
        )

        await interaction.followup.send(embed=embed, ephemeral=True)


class PlaceBetModal(discord.ui.Modal, title="Place Bet"):
    def __init__(self, event_id: int, options: List[str]):
        super().__init__()
        self.event_id = event_id
        self.options = options

        # Create option selector
        options_text = "\n".join(f"{i + 1}. {opt}" for i, opt in enumerate(options))
        self.add_item(discord.ui.TextInput(
            label="Available Options",
            default=options_text,
            style=discord.TextStyle.paragraph,
            required=False
        ))

    option_input = discord.ui.TextInput(
        label="Option Number",
        placeholder="Enter option number (1, 2, 3, etc.)",
        required=True,
        max_length=2
    )

    amount_input = discord.ui.TextInput(
        label="Bet Amount",
        placeholder="Enter amount to bet",
        required=True,
        max_length=10
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            option_num = int(self.option_input.value)
            amount = int(self.amount_input.value.replace(',', ''))

            if option_num < 1 or option_num > len(self.options):
                await interaction.followup.send(f"Invalid option. Must be 1-{len(self.options)}", ephemeral=True)
                return

            if amount < 10:
                await interaction.followup.send("Minimum bet is 10 coins", ephemeral=True)
                return

            betting_cog = interaction.client.get_cog('SimpleBettingCog')
            result = await betting_cog.place_bet(
                interaction.user.id,
                interaction.guild.id,
                self.event_id,
                option_num - 1,  # Convert to 0-based index
                amount
            )

            if result['success']:
                await interaction.followup.send(
                    f"✅ Bet placed!\n"
                    f"Option: {self.options[option_num - 1]}\n"
                    f"Amount: {amount:,} coins\n"
                    f"Remaining coins: {result['remaining_coins']:,}",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(f"❌ {result['reason']}", ephemeral=True)

        except ValueError:
            await interaction.followup.send("Invalid input. Please enter numbers only.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(SimpleBettingCog(bot))