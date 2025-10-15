#!/usr/bin/env python3
"""
B_m2.py — Real-ready Waifu Berry Miner (auto-start CLI, restartable)

Features:
- Automatically starts mining upon launch
- CLI accepts 'start', 'stop', 'exit' — you can pause/resume mining anytime
- Removed CSV saving (only JSON summaries)
"""

import argparse
import asyncio
import json
import logging
import os
import random
import re
import sys
from datetime import datetime

try:
    from telethon import TelegramClient, events
    from telethon.errors import RPCError
    TELETHON_AVAILABLE = True
except Exception:
    TELETHON_AVAILABLE = False

DEFAULT_COMMANDS = ['/dice', '/bowling', '/lever', '/explore']
LOG_DIR = os.path.join('data', 'logs')
SESSION_DIR = os.path.join('data', 'sessions')
SUMMARY_DIR = os.path.join('data', 'summary')
COMMAND_COOLDOWN = 125.0
ALMOST_READY_THRESHOLD = 2.0

RE_BERRIES = re.compile(r'discovered (\d+) Berries|You gained (\d+) Berries|Berries: (\d+)', re.I)
RE_CRYSTALS = re.compile(r'([0-9]+) Crystals|crystal[s]?:? (\d+)', re.I)
RE_WAIFU = re.compile(r'got (?:a |an )?(.+? Waifu)|You obtained (.+? Waifu)', re.I)

def ensure_dirs():
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(SESSION_DIR, exist_ok=True)
    os.makedirs(SUMMARY_DIR, exist_ok=True)

def ts():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def make_logger(session_id):
    ensure_dirs()
    logfile = os.path.join(LOG_DIR, f'{session_id}.log')
    logger = logging.getLogger(f'miner-{session_id}')
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        fh = logging.FileHandler(logfile, encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        fmt = logging.Formatter('[%(asctime)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        fh.setFormatter(fmt)
        logger.addHandler(fh)
        sh = logging.StreamHandler(sys.stdout)
        sh.setLevel(logging.INFO)
        sh.setFormatter(fmt)
        logger.addHandler(sh)
    return logger, logfile

async def simulate_send(session_id, command, logger, summary):
    await asyncio.sleep(random.uniform(0.2, 1.2))
    logger.info(f"{session_id}: sent {command}")
    if command == '/explore':
        berries = random.randint(5, 800)
        text = f"{ts()} [simulated session]: /explore result: 🎉 You uncovered ruins and discovered {berries} Berries! 💰"
        logger.info(text)
        extract_and_record(text, summary, logger)
        return text
    else:
        text = f"{ts()} [simulated session]: {command} result: (simulated)"
        logger.info(text)
        return text

def extract_and_record(text, summary, logger):
    b = RE_BERRIES.search(text)
    if b:
        berries = next((g for g in b.groups() if g), None)
        if berries:
            summary['berries_total'] += int(berries)
            summary['events'].append({'time': ts(), 'type': 'berries', 'amount': int(berries), 'text': text})
            logger.info(f"[parsed] +{berries} Berries (total {summary['berries_total']})")
    c = RE_CRYSTALS.search(text)
    if c:
        crystals = next((g for g in c.groups() if g), None)
        if crystals:
            summary['crystals_total'] += int(crystals)
            summary['events'].append({'time': ts(), 'type': 'crystals', 'amount': int(crystals), 'text': text})
            logger.info(f"[parsed] +{crystals} Crystals (total {summary['crystals_total']})")
    w = RE_WAIFU.search(text)
    if w:
        waifu = next((g for g in w.groups() if g), None)
        if waifu:
            summary['waifus'].append({'time': ts(), 'waifu': waifu, 'text': text})
            summary['events'].append({'time': ts(), 'type': 'waifu', 'name': waifu, 'text': text})
            logger.info(f"[parsed] Got waifu: {waifu}")

class RealClient:
    def __init__(self, api_id, api_hash, session_name, bot_username, logger, summary):
        if not TELETHON_AVAILABLE:
            raise RuntimeError("Telethon is not available. pip install telethon")
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_name = os.path.join(SESSION_DIR, session_name)
        self.bot = bot_username
        self.logger = logger
        self.summary = summary
        self.client = TelegramClient(self.session_name, api_id, api_hash)

    async def start(self):
        await self.client.start()
        self.logger.info(f"{ts()} {self.session_name}: real client started (logged in)")
        if self.bot:
            @self.client.on(events.NewMessage(from_users=self.bot))
            async def bot_handler(ev):
                text = ev.raw_text
                log_text = f"{ts()} {self.session_name}: {self.bot} -> {text}"
                self.logger.info(log_text)
                extract_and_record(log_text, self.summary, self.logger)

    async def send(self, command):
        try:
            if not self.bot:
                self.logger.info(f"{ts()} No bot configured; cannot send {command}")
                return
            await self.client.send_message(self.bot, command)
            self.logger.info(f"{ts()} {self.session_name}: sent {command}")
        except RPCError as e:
            self.logger.info(f"{ts()} {self.session_name}: Error sending {command}: {e}")

    async def stop(self):
        await self.client.disconnect()
        self.logger.info(f"{ts()} {self.session_name}: real client stopped")

class Miner:
    def __init__(self, session_id, commands=None, simulate=True, api_id=None, api_hash=None, bot=None):
        self.session_id = str(session_id)
        self.commands = commands or DEFAULT_COMMANDS.copy()
        self.simulate = simulate
        self.api_id = api_id
        self.api_hash = api_hash
        self.bot = bot
        self.logger, _ = make_logger(self.session_id)
        self.running = False
        self.summary = {'berries_total': 0, 'crystals_total': 0, 'waifus': [], 'events': []}
        self.last_sent = {cmd: datetime.min for cmd in self.commands}
        self.real_client = None
        if not self.simulate and self.api_id and self.api_hash and self.bot:
            if not TELETHON_AVAILABLE:
                raise RuntimeError("Telethon not installed; pip install telethon")
            self.real_client = RealClient(self.api_id, self.api_hash, self.session_id, self.bot, self.logger, self.summary)
        self._task = None

    async def run(self):
        self.running = True
        self.logger.info(f"{ts()} {self.session_id}: miner started")
        if self.real_client:
            await self.real_client.start()
        try:
            while self.running:
                now = datetime.now()
                for cmd in self.commands:
                    if not self.running:
                        break
                    elapsed = (now - self.last_sent[cmd]).total_seconds()
                    remaining = COMMAND_COOLDOWN - elapsed
                    if elapsed >= COMMAND_COOLDOWN:
                        if self.simulate:
                            await simulate_send(self.session_id, cmd, self.logger, self.summary)
                        else:
                            if self.real_client:
                                await self.real_client.send(cmd)
                        self.last_sent[cmd] = datetime.now()
                    else:
                        if remaining < ALMOST_READY_THRESHOLD:
                            self.logger.info(f"{ts()} {self.session_id}: {cmd} almost ready in {remaining:.1f}s")
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            self.logger.info(f"{ts()} {self.session_id}: miner cancelled")
        finally:
            if self.real_client:
                await self.real_client.stop()
            self._write_summary()
            self.logger.info(f"{ts()} {self.session_id}: miner stopped")

    def start(self, loop):
        if not self.running:
            self._task = loop.create_task(self.run())
            print("Miner started.")

    def stop(self):
        if self.running:
            self.running = False
            print("Miner stopped.")

    def is_running(self):
        return self.running

    def _write_summary(self):
        ensure_dirs()
        fname = os.path.join(SUMMARY_DIR, f'{self.session_id}_summary_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
        with open(fname, 'w', encoding='utf-8') as f:
            json.dump(self.summary, f, ensure_ascii=False, indent=2)
        self.logger.info(f"Summary written: {fname}")

async def cli_interface(miner):
    print("Type 'start', 'stop', or 'exit' to control miner.\n")
    loop = asyncio.get_event_loop()
    miner.start(loop)
    while True:
        cmd = await loop.run_in_executor(None, sys.stdin.readline)
        cmd = cmd.strip().lower()
        if cmd == 'start':
            if miner.is_running():
                print("Miner already running.")
            else:
                miner.start(loop)
        elif cmd == 'stop':
            if not miner.is_running():
                print("Miner is not running.")
            else:
                miner.stop()
        elif cmd == 'exit':
            miner.stop()
            if miner._task:
                miner._task.cancel()
                try:
                    await miner._task
                except Exception:
                    pass
            print("Exiting miner.")
            break
        else:
            print("Unknown command. Use: start | stop | exit")

async def main_async(args):
    miner = Miner(
        session_id=args.session,
        commands=args.commands,
        simulate=args.simulate,
        api_id=args.api_id,
        api_hash=args.api_hash,
        bot=args.bot
    )
    if not miner.simulate and not TELETHON_AVAILABLE:
        print("Real mode requested but Telethon not installed. pip install telethon")
        return
    await cli_interface(miner)

def parse_args():
    p = argparse.ArgumentParser(description="Waifu Berry Miner — auto-start CLI, restartable")
    p.add_argument('--session', required=True, help='Session id to identify logs/sessions')
    p.add_argument('--simulate', action='store_true', default=False, help='Run in simulation mode')
    p.add_argument('--api-id', type=int, help='Telegram API ID (for real mode)')
    p.add_argument('--api-hash', help='Telegram API Hash (for real mode)')
    p.add_argument('--bot', help='Bot username (e.g. @YamatoAcn_bot) for real mode')
    p.add_argument('--commands', nargs='+', default=DEFAULT_COMMANDS, help='Commands to cycle through')
    return p.parse_args()

def main():
    args = parse_args()
    if not args.simulate and not (args.api_id and args.api_hash and args.bot):
        print("Missing Telethon info — defaulting to simulation mode.")
        args.simulate = True
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("Interrupted — exiting.")

if __name__ == '__main__':
    main()


# python B_m2.py --session 6503568906 --api-id 22909508 --api-hash e4edd9c94fc33e0bddc6089f7fd7664a --bot "@YamatoAcn_bot"