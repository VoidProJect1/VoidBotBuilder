# ⚡ VOID BOT BUILDER BOT

> The most powerful Telegram bot factory. Build, Deploy & Manage 8 different bot types in seconds.

---

## 🛍️ 8 Premium Templates

| # | Template | Category | Highlight |
|---|----------|----------|-----------|
| 1 | 💎 Polygon Auto Pay Bot | Crypto | Earn real MATIC + Reply Keyboard |
| 2 | 🎁 Refer & Earn Bot | Referral | Coins + Leaderboard |
| 3 | 🚀 Advanced Refer & Earn | Referral | Multi-tier + Ranks + Shop |
| 4 | 🎯 Quiz & Trivia Bot | Games | 5 categories + polls |
| 5 | 📢 Mass Broadcast Bot | Marketing | Unlimited subscribers |
| 6 | 👋 Group Welcome Manager | Groups | Auto-welcome + moderation |
| 7 | 🎰 Lucky Draw & Lottery Bot | Giveaway | Ticket system + fair draw |
| 8 | 🛒 Mini Shop Bot | E-Commerce | Full store + orders |

---

## 📦 Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure
# Edit config.py — add your builder bot token + your Telegram user ID

# 3. Run
python main.py
```

---

## ⚙️ config.py

```python
BUILDER_TOKEN = "YOUR_BUILDER_BOT_TOKEN"   # From @BotFather
ADMIN_IDS     = [YOUR_TELEGRAM_USER_ID]     # Your numeric ID
```

---

## 💎 Polygon Auto Pay Bot — Special Notes

This template features:
- **Reply Keyboard** at the bottom (Withdraw, Refer & Earn, Set POL Wallet, Balance, Stats, Help, Features)
- **Force-join** channel verification before unlock
- Admin can set channels: `/addchannel @channel`
- Admin can set MATIC rate: `/setrate 0.1`
- Withdrawal requests go to admin for approval

---

## 🗂️ Project Structure

```
void_bot_builder/
├── main.py                  ⚡ Main Void Builder Bot
├── config.py                ⚙️ Configuration
├── database.py              🗄️ SQLite manager
├── bot_manager.py           🔧 Multi-bot orchestrator
├── requirements.txt
├── README.md
└── templates/
    ├── __init__.py          📋 8-template registry
    ├── base.py              🔧 Base class
    ├── polygon_pay.py       💎 Polygon Auto Pay
    ├── refer_earn.py        🎁 Refer & Earn
    ├── adv_refer.py         🚀 Advanced Refer
    ├── quiz_bot.py          🎯 Quiz Bot
    ├── broadcast_bot.py     📢 Broadcast Bot
    ├── welcome_bot.py       👋 Welcome Manager
    ├── lucky_draw.py        🎰 Lucky Draw
    └── mini_shop.py         🛒 Mini Shop
```

---

## 🤖 Builder Bot Commands

| Command | Action |
|---------|--------|
| `/start` | ⚡ Main menu |
| `/addbot` | ➕ Deploy a new bot |
| `/mybots` | 🤖 View & manage bots |
| `/stats` | 📊 Global statistics |
| `/help` | ❓ Help guide |

---

## 🏗️ How Hosting Works

Each deployed bot runs as an isolated **asyncio Task** inside the builder process:
- All bots share the single SQLite database (separate tables per bot)
- Bots auto-restart when the builder restarts
- Start/Stop/Restart from the My Bots panel
- Real-time stats tracked per bot

---

Made with ⚡ **VOID BOT BUILDER**
