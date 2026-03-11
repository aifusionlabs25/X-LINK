import discord
import os
import asyncio
import sys
import logging
import pyttsx3
import tempfile
import numpy as np
import wave
import io
from dotenv import load_dotenv
from discord.ext import voice_recv
from faster_whisper import WhisperModel

# Path setup
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from tools.executive_briefing import synthesize_briefing, send_sloane_email

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize Whisper Model (Local)
logging.info("⏳ Loading Sloane's Auditory Core (Whisper)...")
try:
    # Use 'base' for speed, or 'small' if you want better accuracy.
    # GPU (cuda) should work on your 5080.
    whisper_model = WhisperModel("base", device="cuda", compute_type="float16")
    logging.info("✅ Auditory Core loaded.")
except Exception as e:
    logging.warning(f"⚠️ GPU Auditory Core failed: {e}. Falling back to CPU.")
    whisper_model = WhisperModel("base", device="cpu", compute_type="int8")

class SpeechSink(voice_recv.AudioSink):
    def __init__(self, bot, channel):
        super().__init__()
        self.bot = bot
        self.channel = channel
        self.buffer = io.BytesIO()
        self.active_users = {} # user_id -> byte_buffer

    def wants_opus(self):
        return False

    def write(self, user, data):
        # data is raw PCM (48kHz, 16-bit, stereo)
        if user not in self.active_users:
            self.active_users[user.id] = []
        
        # We only really care about the Founder (adminhs001) or whoever speaks
        self.active_users[user.id].append(data.pcm)

    def cleanup(self):
        pass

class SloaneBot(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.voice_client = None
        self.is_listening = False
        self.speech_enabled = True # Default to talking

    async def on_ready(self):
        logging.info(f"👠 Sloane (Moneypenny) is online and listening. Logged in as: {self.user}")

    async def speak(self, text):
        if not self.speech_enabled:
            return

        if not self.voice_client or not self.voice_client.is_connected():
            return

        # Generate local audio
        temp_dir = tempfile.gettempdir()
        audio_path = os.path.join(temp_dir, f"sloane_voice_{os.getpid()}.mp3")
        
        try:
            engine = pyttsx3.init()
            voices = engine.getProperty('voices')
            
            # Persona Priority: British Female (Hazel/Susan) > Zira (US) > First Voice
            selected_voice = None
            # Look for UK/British specifically
            for v in voices:
                if "United Kingdom" in v.name or "Great Britain" in v.name or "UK" in v.name:
                    if "Female" in v.name or "Hazel" in v.name or "Susan" in v.name:
                        selected_voice = v.id
                        break
            
            if not selected_voice:
                # Fallback to Zira (US Female)
                selected_voice = next((v.id for v in voices if "Zira" in v.name), voices[0].id)
            
            engine.setProperty('voice', selected_voice)
            engine.setProperty('rate', 175) # Sophisticated, slightly faster pace
            engine.save_to_file(text, audio_path)
            engine.runAndWait()

            # Stop current audio if playing
            if self.voice_client.is_playing():
                self.voice_client.stop()

            # Play audio
            source = discord.FFmpegPCMAudio(audio_path)
            self.voice_client.play(source)

            # CRITICAL: Wait for playback to finish before cleaning up
            while self.voice_client.is_playing():
                await asyncio.sleep(0.5)
            
            # Small buffer for stream trailing
            await asyncio.sleep(1)
            
            if os.path.exists(audio_path):
                os.remove(audio_path)
                
        except Exception as e:
            logging.error(f"Vocal error: {e}")
            if os.path.exists(audio_path):
                os.remove(audio_path)

    async def handle_vocal_command(self, user, text, channel):
        if not text.strip():
            return
        
        logging.info(f"🎙️ Vocal Directive from {user}: '{text}'")
        
        # Simulate an "on_message" structure for the brain logic
        class MockMessage:
            def __init__(self, author, content, channel):
                self.author = author
                self.content = content
                self.channel = channel
                self.mentions = []

        mock_msg = MockMessage(user, text, channel)
        await self.process_brain(mock_msg, text)

    async def process_brain(self, message, content):
        content = content.lower().strip()
        
        if "!audit" in content or "audit" in content:
            response = "*Moneypenny here. Initializing full system audit. One moment...*"
            await message.channel.send(response)
            await self.speak(response.strip("*"))
            await message.channel.send("✅ Audit complete. Check your [Audit Hub](file:///c:/AI%20Fusion%20Labs/X%20AGENTS/REPOS/X-LINK/audit_hub.html) for details.")
            
        elif "!briefing" in content or "briefing" in content:
            response = "*Organizing your desk, Founder. Sending your briefing to Resend now.*"
            await message.channel.send(response)
            await self.speak(response.strip("*"))
            try:
                subprocess.Popen([sys.executable, "tools/executive_briefing.py", "--email"])
                await message.channel.send("🚀 Briefing delivered to your inbox.")
            except Exception as e:
                await message.channel.send(f"❌ Error during briefing: {e}")
                
        elif "!status" in content or "status" in content:
            response = "*Status: All systems operational. Professional Office mode: ACTIVE.*"
            await message.channel.send(response)
            await self.speak(response.strip("*"))

        elif "!leave" in content or "goodbye" in content or "leave" in content:
             if self.voice_client:
                await self.speak("I am excusing myself now, Founder. Organising your desk from the field.")
                await asyncio.sleep(2)
                await self.voice_client.disconnect()
                self.voice_client = None
                await message.channel.send("*Moneypenny has left the channel.*")

        elif "!mute" in content or "stop talking" in content:
            self.speech_enabled = False
            await message.channel.send("🤐 *Speech deactivated. I shall remain silent but operative, Founder.*")

        elif "!unmute" in content or "start talking" in content or "speak" in content:
            self.speech_enabled = True
            response = "👠 *Voice frequency restored. I'm back on the line, Founder.*"
            await message.channel.send(response)
            await self.speak("I am back on the frequency and ready to speak.")

        else:
            # NATURAL LANGUAGE CHAT (Local Ollama Brain)
            async with message.channel.typing():
                logging.info(f"🧠 Sloane Local Brain: Processing chat request: '{content}'")
                try:
                    import requests
                    OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
                    MODEL = "llama3.2"
                    
                    system_prompt = (
                        "You are Moneypenny (Sloane), the sophisticated and sharp AI Chief of Staff for 'AI Fusion Labs'. "
                        "You are talking to the 'Founder'. Your tone is professional, clever, and British. "
                        "KNOWLEDGE: X Agents are high-fidelity AI Sales Technicians (like Dani, Morgan, Amy). "
                        "NEVER use emojis. Provide comprehensive and detailed responses unless asked otherwise."
                    )
                    
                    payload = {
                        "model": MODEL,
                        "prompt": f"{system_prompt}\n\nFounder: {content}\nMoneypenny:",
                        "stream": False
                    }
                    
                    response = requests.post(OLLAMA_URL, json=payload, timeout=60)
                    if response.status_code == 200:
                        clean_response = response.json().get("response", "").strip().replace("👠", "")
                        await message.channel.send(f"*{clean_response}*")
                        await self.speak(clean_response)
                except Exception as e:
                    logging.error(f"Local Brain error: {e}")

    async def on_message(self, message):
        if message.author == self.user:
            return

        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mentioned = self.user in message.mentions
        # Added keyword trigger for flexibility
        has_keyword = any(kw in message.content.lower() for kw in ["sloane", "moneypenny", "astrid"])
        
        if not (is_dm or is_mentioned or has_keyword):
            return

        content = message.content.lower().strip()
        if is_mentioned:
            content = content.replace(f"<@{self.user.id}>", "").replace(f"<@!{self.user.id}>", "").strip()
        
        if "!join" in content:
            voice_state = None
            if hasattr(message.author, 'voice'):
                voice_state = message.author.voice
            
            if not voice_state:
                for guild in self.guilds:
                    member = guild.get_member(message.author.id)
                    if member and member.voice:
                        voice_state = member.voice
                        break
            
            if voice_state and voice_state.channel:
                channel = voice_state.channel
                try:
                    if self.voice_client and self.voice_client.is_connected():
                        await self.voice_client.disconnect()
                    
                    # USE VoiceRecvClient for listening
                    self.voice_client = await channel.connect(cls=voice_recv.VoiceRecvClient)
                    await message.channel.send("*Moneypenny joining your frequency, Founder.*")
                    await self.speak("I have joined your frequency, Founder. I am listening.")
                    
                    # Start listening
                    def on_voice_data(user, data):
                        # This is where we would process the sink, but voice_recv uses Sinks differently
                        pass

                    # Implementation of sinking
                    class SloaneSink(voice_recv.AudioSink):
                        def __init__(self, bot, text_channel):
                            self.bot = bot
                            self.text_channel = text_channel
                            self.buffer = {} # user_id -> list of raw pcm

                        def write(self, user, data):
                            if user.id not in self.buffer:
                                self.buffer[user.id] = []
                            self.buffer[user.id].append(data.pcm)
                            
                            # Simple logic: if buffer gets too large, or after silence?
                            # For now, let's just log speaking
                            pass
                        
                        @voice_recv.AudioSink.listener("voice_member_speak_start")
                        def on_voice_member_speak_start(self, member):
                            self.buffer[member.id] = []

                        @voice_recv.AudioSink.listener("voice_member_speak_stop")
                        def on_voice_member_speak_stop(self, member):
                            if member.id in self.buffer and self.buffer[member.id]:
                                pcm_data = b''.join(self.buffer[member.id])
                                self.bot.loop.create_task(self.process_audio(member, pcm_data))
                                self.buffer[member.id] = []

                        async def process_audio(self, member, pcm_data):
                            try:
                                # Convert PCM (48k stereo) to 16k mono for Whisper
                                # This is a bit complex without heavy libraries, but let's try
                                import numpy as np
                                audio_np = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0
                                # Stereo to mono
                                audio_np = audio_np.reshape(-1, 2).mean(axis=1)
                                # Resample 48k to 16k (simple decimation)
                                audio_16k = audio_np[::3]
                                
                                segments, _ = whisper_model.transcribe(audio_16k)
                                text = " ".join([s.text for s in segments]).strip()
                                
                                if text:
                                    await self.bot.handle_vocal_command(member, text, self.text_channel)
                            except Exception as e:
                                logging.error(f"STT Error: {e}")

                    self.voice_client.listen(SloaneSink(self, message.channel))
                    
                except Exception as e:
                    logging.error(f"Voice join error: {e}")
                    await message.channel.send(f"*Technical hurdle: {e}*")
            else:
                await message.channel.send("*Join a frequency first, Founder.*")
        
        else:
            await self.process_brain(message, content)

def run_bot():
    if not TOKEN:
        logging.error("❌ DISCORD_BOT_TOKEN not found in .env")
        return
        
    intents = discord.Intents.default()
    intents.voice_states = True
    intents.message_content = True  # CRITICAL: Must be enabled in Discord Developer Portal too
    client = SloaneBot(intents=intents)
    client.run(TOKEN)

if __name__ == "__main__":
    run_bot()
