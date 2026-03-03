"""
Discord 음성방 슬래시 커맨드 봇
- /입장 [채널명]  → 지정 음성 채널 입장
- /퇴장           → 음성 채널 퇴장
- /상태           → 현재 봇 상태 확인

설치:
    pip install discord.py

실행:
    python discord_stay_bot.py
"""

import discord
import asyncio
from discord import app_commands
import os
import sqlite3
from datetime import datetime

# ──────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────
TOKEN = os.getenv("DISCORD_TOKEN", "여기에_봇_토큰_입력")
VOICE_CHANNEL_ID = int(os.getenv("VOICE_CHANNEL_ID", "0"))  # Railway 환경변수로 설정
DB_PATH = "voice_log.db"

# ──────────────────────────────────────────────
# DB 초기화
# ──────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS voice_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            username TEXT,
            channel_id TEXT,
            channel_name TEXT,
            joined_at TEXT,
            left_at TEXT,
            duration_seconds INTEGER
        )
    """)
    conn.commit()
    conn.close()

def log_join(user_id, username, channel_id, channel_name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO voice_sessions (user_id, username, channel_id, channel_name, joined_at)
        VALUES (?, ?, ?, ?, ?)
    """, (str(user_id), username, str(channel_id), channel_name, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

def log_leave(user_id, channel_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.utcnow()
    c.execute("""
        SELECT id, joined_at FROM voice_sessions
        WHERE user_id = ? AND channel_id = ? AND left_at IS NULL
        ORDER BY id DESC LIMIT 1
    """, (str(user_id), str(channel_id)))
    row = c.fetchone()
    if row:
        session_id, joined_at = row
        joined_dt = datetime.fromisoformat(joined_at)
        duration = int((now - joined_dt).total_seconds())
        c.execute("""
            UPDATE voice_sessions SET left_at = ?, duration_seconds = ?
            WHERE id = ?
        """, (now.isoformat(), duration, session_id))
        conn.commit()
    conn.close()

# ──────────────────────────────────────────────
# 봇 설정
# ──────────────────────────────────────────────
intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True

class StayBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()  # 슬래시 커맨드 글로벌 등록
        print("[슬래시 커맨드 등록 완료]")

    async def on_ready(self):
        init_db()
        print(f"[봇 시작] {self.user} 로그인 완료")
        await self.change_presence(activity=discord.Activity(
            type=discord.ActivityType.listening,
            name="/입장 | /퇴장"
        ))
        # 캐시 로딩 대기 후 자동 입장
        await asyncio.sleep(3)
        channel = self.get_channel(VOICE_CHANNEL_ID)
        if channel and isinstance(channel, discord.VoiceChannel):
            await channel.connect(self_deaf=True, self_mute=True)
            print(f"[자동 입장] {channel.name} 채널에 입장했습니다.")
        else:
            print(f"[경고] VOICE_CHANNEL_ID({VOICE_CHANNEL_ID})를 찾을 수 없습니다.")

    async def on_voice_state_update(self, member, before, after):
        if member.id == self.user.id:
            return

        # 입장 기록
        if after.channel:
            log_join(member.id, str(member), after.channel.id, after.channel.name)
            print(f"[입장] {member} → {after.channel.name}")

        # 퇴장 기록
        if before.channel:
            log_leave(member.id, before.channel.id)
            print(f"[퇴장] {member} ← {before.channel.name}")


bot = StayBot()

# ──────────────────────────────────────────────
# 슬래시 커맨드
# ──────────────────────────────────────────────

@bot.tree.command(name="입장", description="봇을 음성 채널에 입장시킵니다.")
@app_commands.describe(채널="입장할 음성 채널 (비워두면 현재 접속 중인 채널)")
async def enter(interaction: discord.Interaction, 채널: discord.VoiceChannel = None):
    await interaction.response.defer(ephemeral=False)

    # 채널 지정 없으면 사용자가 있는 채널로
    target = 채널
    if target is None:
        if interaction.user.voice and interaction.user.voice.channel:
            target = interaction.user.voice.channel
        else:
            await interaction.followup.send("❌ 음성 채널을 지정하거나, 음성 채널에 먼저 입장해주세요.")
            return

    # 이미 같은 채널에 있으면
    if interaction.guild.voice_client and interaction.guild.voice_client.channel == target:
        await interaction.followup.send(f"✅ 이미 **{target.name}** 채널에 있습니다!")
        return

    try:
        if interaction.guild.voice_client:
            await interaction.guild.voice_client.move_to(target)
        else:
            await target.connect(self_deaf=True, self_mute=True)

        log_join("BOT", str(bot.user), target.id, target.name)
        await interaction.followup.send(f"🎙️ **{target.name}** 채널에 입장했습니다!")
    except Exception as e:
        await interaction.followup.send(f"❌ 입장 실패: {e}")


@bot.tree.command(name="퇴장", description="봇을 음성 채널에서 퇴장시킵니다.")
async def leave(interaction: discord.Interaction):
    vc = interaction.guild.voice_client

    if vc is None or not vc.is_connected():
        await interaction.response.send_message("❌ 봇이 현재 음성 채널에 없습니다.", ephemeral=True)
        return

    channel_name = vc.channel.name
    log_leave("BOT", vc.channel.id)
    await vc.disconnect()
    await interaction.response.send_message(f"👋 **{channel_name}** 채널에서 퇴장했습니다.")


@bot.tree.command(name="상태", description="봇의 현재 음성 채널 상태를 확인합니다.")
async def status(interaction: discord.Interaction):
    vc = interaction.guild.voice_client

    if vc and vc.is_connected():
        members = [m for m in vc.channel.members if not m.bot]
        await interaction.response.send_message(
            f"📡 현재 **{vc.channel.name}** 채널에 상주 중\n"
            f"👥 사용자 수: {len(members)}명",
            ephemeral=True
        )
    else:
        await interaction.response.send_message("💤 현재 음성 채널에 없습니다.", ephemeral=True)


bot.run(TOKEN)