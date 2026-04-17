"""⚡ Void Bot Builder — Templates Registry (8 Templates)"""

from .polygon_pay    import PolygonPayBot
from .refer_earn     import ReferEarnBot
from .adv_refer      import AdvancedReferBot
from .quiz_bot       import QuizBot
from .broadcast_bot  import BroadcastBot
from .welcome_bot    import WelcomeBot
from .lucky_draw     import LuckyDrawBot
from .mini_shop      import MiniShopBot

BOT_TEMPLATES = {
    "polygon_pay": {
        "name": "Polygon Auto Pay Bot",
        "emoji": "💎",
        "stars": 3,
        "new": True,
        "category": "Crypto / Payments",
        "description": "Auto-pay referral system using Polygon (MATIC). Users earn MATIC for referrals. Force-join channels, set POL wallet, withdraw to wallet.",
        "features": [
            "💰 Earn MATIC per referral",
            "🔗 Force-join channel verification",
            "👛 Set Polygon (POL) wallet address",
            "💸 Automatic withdrawal system",
            "📊 Balance & earnings tracker",
            "🏆 Referral leaderboard",
            "✨ Features showcase panel",
            "📢 Reply keyboard menu (like screenshot)",
            "👑 Admin payout dashboard",
            "🛡️ Anti-cheat protection",
        ],
        "complexity": "🔥 Advanced",
        "best_for": "Crypto communities, DeFi projects",
    },
    "refer_earn": {
        "name": "Refer & Earn Bot",
        "emoji": "🎁",
        "stars": 2,
        "category": "Referral",
        "description": "Simple but powerful coin-based referral system with leaderboard and withdrawal.",
        "features": [
            "🔗 Unique referral link per user",
            "🪙 Coins per referral",
            "🏆 Top referrers leaderboard",
            "💸 Withdrawal request panel",
            "👑 Admin approval system",
            "🛡️ Anti-fake protection",
        ],
        "complexity": "⚡ Beginner",
        "best_for": "Small communities, side projects",
    },
    "adv_refer": {
        "name": "Advanced Refer & Earn",
        "emoji": "🚀",
        "stars": 3,
        "category": "Referral",
        "description": "Multi-tier referral tree with rank system, daily check-in, milestones, and a full reward shop.",
        "features": [
            "🌳 3-level referral tree (L1/L2/L3)",
            "🏅 Ranks: Bronze→Silver→Gold→Diamond",
            "📅 Daily check-in with streak bonus",
            "🏆 Milestone rewards (10/25/50/100 refs)",
            "🛒 Reward shop (redeem coins)",
            "📊 Real-time leaderboard",
            "👑 Admin dashboard",
            "🛡️ Anti-cheat cooldowns",
        ],
        "complexity": "🔥 Advanced",
        "best_for": "Large communities, campaigns",
    },
    "quiz_bot": {
        "name": "Quiz & Trivia Bot",
        "emoji": "🎯",
        "stars": 2,
        "category": "Entertainment",
        "description": "Interactive quiz with 5 categories, timed questions (Telegram polls), scoring & leaderboard.",
        "features": [
            "❓ 5 quiz categories",
            "⏱️ Timed questions (15 seconds)",
            "📊 Score & streak tracking",
            "🏆 Global leaderboard",
            "➕ Admin add custom questions",
            "🎁 Daily challenge reward",
        ],
        "complexity": "⚡ Intermediate",
        "best_for": "Education, entertainment",
    },
    "broadcast_bot": {
        "name": "Mass Broadcast Bot",
        "emoji": "📢",
        "stars": 2,
        "category": "Marketing",
        "description": "Collect unlimited subscribers and blast messages to all of them instantly.",
        "features": [
            "✅ Auto-subscribe on /start",
            "📨 Text, photo, video broadcasts",
            "📊 Delivery stats (sent/failed)",
            "🔕 User unsubscribe option",
            "👑 Admin-only broadcast panel",
            "📅 Scheduled broadcast (coming soon)",
        ],
        "complexity": "⚡ Beginner",
        "best_for": "Channels, newsletters",
    },
    "welcome_bot": {
        "name": "Group Welcome Manager",
        "emoji": "👋",
        "stars": 1,
        "category": "Group Tools",
        "description": "Auto-welcome new members, farewell departing ones, anti-spam, admin commands.",
        "features": [
            "👋 Custom welcome messages",
            "😢 Farewell messages",
            "📋 Group rules (/rules)",
            "🚫 Anti-spam & link filter",
            "🔇 Mute / 👢 Kick / 🚫 Ban",
            "⚙️ Per-group settings",
        ],
        "complexity": "⚡ Beginner",
        "best_for": "Telegram groups",
    },
    "lucky_draw": {
        "name": "Lucky Draw & Lottery Bot",
        "emoji": "🎰",
        "stars": 3,
        "new": True,
        "category": "Games / Giveaway",
        "description": "Run viral lotteries and lucky draws. Users buy tickets, winner picked randomly. Full admin control.",
        "features": [
            "🎟️ Ticket-based entry system",
            "🎲 Fair random winner selection",
            "⏰ Timed draw countdown",
            "🏆 Winner announcement broadcast",
            "💰 Prize pool display",
            "📊 Participants list",
            "🔁 Multi-round support",
            "👑 Admin create/manage draws",
            "🛡️ One ticket per user protection",
            "🎊 Animated winner reveal",
        ],
        "complexity": "🔥 Intermediate",
        "best_for": "Giveaways, viral marketing",
    },
    "mini_shop": {
        "name": "Mini Shop Bot",
        "emoji": "🛒",
        "stars": 2,
        "new": True,
        "category": "E-Commerce",
        "description": "A complete mini-store inside Telegram. Add products, accept orders, manage inventory.",
        "features": [
            "🛍️ Product catalog with photos",
            "🛒 Shopping cart system",
            "📦 Order management panel",
            "💳 Manual payment confirmation",
            "📊 Sales analytics",
            "🔔 Order notifications to admin",
            "📝 Order history per user",
            "⚙️ Admin add/edit/remove products",
            "📱 Mobile-friendly inline UI",
            "🏷️ Category filtering",
        ],
        "complexity": "🔥 Advanced",
        "best_for": "Small businesses, digital products",
    },
}


def get_template_info(tid: str) -> dict:
    return BOT_TEMPLATES.get(tid)

def get_template_class(tid: str):
    return {
        "polygon_pay":   PolygonPayBot,
        "refer_earn":    ReferEarnBot,
        "adv_refer":     AdvancedReferBot,
        "quiz_bot":      QuizBot,
        "broadcast_bot": BroadcastBot,
        "welcome_bot":   WelcomeBot,
        "lucky_draw":    LuckyDrawBot,
        "mini_shop":     MiniShopBot,
    }.get(tid)
