import os
import sqlite3
from datetime import datetime, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ChatMemberHandler,
    MessageHandler,
    filters,
)

# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

OWNER_ID = 8762217575
OWNER_USERNAME = "wabillah"

DB_FILE = "pincycle.db"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in Railway Variables.")


# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(DB_FILE, check_same_thread=False)
db.row_factory = sqlite3.Row

db.execute("PRAGMA journal_mode=WAL")

db.executescript(
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        has_access INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS groups (
        chat_id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        added_by INTEGER NOT NULL,
        added_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS pending_pins (
        chat_id INTEGER PRIMARY KEY,
        hours INTEGER NOT NULL,
        created_at TEXT NOT NULL
    );
    """
)

db.commit()


def now():
    return datetime.now(timezone.utc).isoformat()


# =========================================================
# USER FUNCTIONS
# =========================================================

def save_user(user):
    username = (user.username or "").lower()

    db.execute(
        """
        INSERT INTO users (user_id, username)
        VALUES (?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET username = excluded.username
        """,
        (user.id, username),
    )

    db.commit()


def user_has_access(user_id):
    if user_id == OWNER_ID:
        return True

    row = db.execute(
        "SELECT has_access FROM users WHERE user_id = ?",
        (user_id,),
    ).fetchone()

    return bool(row and row["has_access"])


def grant_access(username):
    username = username.replace("@", "").lower()

    row = db.execute(
        """
        SELECT user_id
        FROM users
        WHERE LOWER(username) = ?
        """,
        (username,),
    ).fetchone()

    if not row:
        return None

    db.execute(
        """
        UPDATE users
        SET has_access = 1
        WHERE user_id = ?
        """,
        (row["user_id"],),
    )

    db.commit()

    return row["user_id"]


def remove_access(username):
    username = username.replace("@", "").lower()

    row = db.execute(
        """
        SELECT user_id
        FROM users
        WHERE LOWER(username) = ?
        """,
        (username,),
    ).fetchone()

    if not row:
        return None

    if row["user_id"] == OWNER_ID:
        return row["user_id"]

    db.execute(
        """
        UPDATE users
        SET has_access = 0
        WHERE user_id = ?
        """,
        (row["user_id"],),
    )

    db.commit()

    return row["user_id"]


# =========================================================
# GROUP FUNCTIONS
# =========================================================

def add_group(chat_id, title, user_id):
    db.execute(
        """
        INSERT INTO groups
        (chat_id, title, added_by, added_at)
        VALUES (?, ?, ?, ?)

        ON CONFLICT(chat_id)
        DO UPDATE SET
            title = excluded.title,
            added_by = excluded.added_by
        """,
        (
            chat_id,
            title,
            user_id,
            now(),
        ),
    )

    db.commit()


def remove_group(chat_id, user_id):
    db.execute(
        """
        DELETE FROM groups
        WHERE chat_id = ?
        AND added_by = ?
        """,
        (
            chat_id,
            user_id,
        ),
    )

    db.execute(
        """
        DELETE FROM pending_pins
        WHERE chat_id = ?
        """,
        (chat_id,),
    )

    db.commit()


def get_groups(user_id):
    return db.execute(
        """
        SELECT chat_id, title
        FROM groups
        WHERE added_by = ?
        ORDER BY title
        """,
        (user_id,),
    ).fetchall()


# =========================================================
# KEYBOARDS
# =========================================================

def main_menu():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "➕ Add Group",
                    callback_data="add_group",
                ),
                InlineKeyboardButton(
                    "📂 My Group",
                    callback_data="my_group",
                ),
            ],
            [
                InlineKeyboardButton(
                    "📋 Useful Commands",
                    callback_data="commands",
                ),
                InlineKeyboardButton(
                    "👤 Contact Owner",
                    url=f"https://t.me/{OWNER_USERNAME}",
                ),
            ],
        ]
    )


def back_button(callback="home"):

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔙 Back",
                    callback_data=callback,
                )
            ]
        ]
    )


def contact_owner_button():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "👤 Contact Owner",
                    url=f"https://t.me/{OWNER_USERNAME}",
                )
            ]
        ]
    )


# =========================================================
# ACCESS DENIED
# =========================================================

def access_denied_text():

    return (
        "❌ You don't have access to use Pin Cycle.\n\n"
        "Please contact the owner to request access."
    )


# =========================================================
# /START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    save_user(user)

    if not user_has_access(user.id):

        await update.message.reply_text(
            access_denied_text(),
            reply_markup=contact_owner_button(),
        )

        return

    await update.message.reply_text(
        "📌 Pin Cycle",
        reply_markup=main_menu(),
    )


# =========================================================
# /ACCESS
# =========================================================

async def access_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    save_user(user)

    if user.id != OWNER_ID:
        return

    if not context.args:

        await update.message.reply_text(
            "Usage:\n/access @username"
        )

        return

    username = context.args[0]

    target = grant_access(username)

    if target is None:

        await update.message.reply_text(
            "❌ User not found.\n\n"
            "Ask the user to open the bot and press /start first."
        )

        return

    await update.message.reply_text(
        f"✅ Access granted to {username}."
    )


# =========================================================
# /REMOVEACCESS
# =========================================================

async def remove_access_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    save_user(user)

    if user.id != OWNER_ID:
        return

    if not context.args:

        await update.message.reply_text(
            "Usage:\n/removeaccess @username"
        )

        return

    username = context.args[0]

    target = remove_access(username)

    if target is None:

        await update.message.reply_text(
            "❌ User not found."
        )

        return

    await update.message.reply_text(
        f"✅ Access removed from {username}."
    )


# =========================================================
# INLINE BUTTONS
# =========================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    user = query.from_user

    save_user(user)

    # -----------------------------------------------------
    # ACCESS CHECK
    # -----------------------------------------------------

    if not user_has_access(user.id):

        await query.edit_message_text(
            access_denied_text(),
            reply_markup=contact_owner_button(),
        )

        return

    data = query.data

    # =====================================================
    # HOME
    # =====================================================

    if data == "home":

        await query.edit_message_text(
            "📌 Pin Cycle",
            reply_markup=main_menu(),
        )

        return

    # =====================================================
    # ADD GROUP
    # =====================================================

    if data == "add_group":

        groups = get_groups(user.id)

        if not groups:

            await query.edit_message_text(
                "➕ Add Group\n\n"
                "No group is available yet.\n\n"
                "Add PinCycleBOT to your group as an admin "
                "and give it permission to pin messages.\n\n"
                "After that, use /pin 4h, /pin 8h, "
                "/pin 12h or /pin 24h in the group.",
                reply_markup=back_button("home"),
            )

            return

        buttons = []

        for group in groups:

            buttons.append(
                [
                    InlineKeyboardButton(
                        group["title"][:50],
                        callback_data=f"select_group:{group['chat_id']}",
                    )
                ]
            )

        buttons.append(
            [
                InlineKeyboardButton(
                    "🔙 Back",
                    callback_data="home",
                )
            ]
        )

        await query.edit_message_text(
            "➕ Select Group",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

        return

    # =====================================================
    # SELECT GROUP
    # =====================================================

    if data.startswith("select_group:"):

        chat_id = int(
            data.split(":", 1)[1]
        )

        group = db.execute(
            """
            SELECT title
            FROM groups
            WHERE chat_id = ?
            AND added_by = ?
            """,
            (
                chat_id,
                user.id,
            ),
        ).fetchone()

        if not group:

            await query.edit_message_text(
                "❌ Group not found.",
                reply_markup=back_button("add_group"),
            )

            return

        await query.edit_message_text(
            f"✅ {group['title']} is ready.\n\n"
            "Use one of these commands in the group:\n\n"
            "`/pin 4h`\n"
            "`/pin 8h`\n"
            "`/pin 12h`\n"
            "`/pin 24h`",
            parse_mode="Markdown",
            reply_markup=back_button("home"),
        )

        return

    # =====================================================
    # MY GROUP
    # =====================================================

    if data == "my_group":

        groups = get_groups(user.id)

        if not groups:

            await query.edit_message_text(
                "📂 My Groups\n\n"
                "No groups added yet.",
                reply_markup=back_button("home"),
            )

            return

        buttons = []

        for group in groups:

            buttons.append(
                [
                    InlineKeyboardButton(
                        group["title"][:50],
                        callback_data=f"group_info:{group['chat_id']}",
                    )
                ]
            )

        # REMOVE GROUP ONLY ONCE
        buttons.append(
            [
                InlineKeyboardButton(
                    "🗑 Remove Group",
                    callback_data="remove_group",
                )
            ]
        )

        # BACK UNDER REMOVE GROUP
        buttons.append(
            [
                InlineKeyboardButton(
                    "🔙 Back",
                    callback_data="home",
                )
            ]
        )

        await query.edit_message_text(
            "📂 My Groups",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

        return

    # =====================================================
    # GROUP INFO
    # =====================================================

    if data.startswith("group_info:"):

        chat_id = int(
            data.split(":", 1)[1]
        )

        group = db.execute(
            """
            SELECT title
            FROM groups
            WHERE chat_id = ?
            AND added_by = ?
            """,
            (
                chat_id,
                user.id,
            ),
        ).fetchone()

        if not group:

            await query.edit_message_text(
                "❌ Group not found.",
                reply_markup=back_button("my_group"),
            )

            return

        await query.edit_message_text(
            f"📂 {group['title']}\n\n"
            "Pin commands:\n\n"
            "`/pin 4h`\n"
            "`/pin 8h`\n"
            "`/pin 12h`\n"
            "`/pin 24h`",
            parse_mode="Markdown",
            reply_markup=back_button("my_group"),
        )

        return

    # =====================================================
    # REMOVE GROUP
    # =====================================================

    if data == "remove_group":

        groups = get_groups(user.id)

        if not groups:

            await query.edit_message_text(
                "🗑 No groups to remove.",
                reply_markup=back_button("my_group"),
            )

            return

        buttons = []

        for group in groups:

            buttons.append(
                [
                    InlineKeyboardButton(
                        f"🗑 {group['title'][:45]}",
                        callback_data=f"remove:{group['chat_id']}",
                    )
                ]
            )

        buttons.append(
            [
                InlineKeyboardButton(
                    "🔙 Back",
                    callback_data="my_group",
                )
            ]
        )

        await query.edit_message_text(
            "🗑 Select a group to remove:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

        return

    # =====================================================
    # REMOVE SELECTED GROUP
    # =====================================================

    if data.startswith("remove:"):

        chat_id = int(
            data.split(":", 1)[1]
        )

        remove_group(
            chat_id,
            user.id,
        )

        await query.edit_message_text(
            "✅ Group removed.",
            reply_markup=back_button("my_group"),
        )

        return

    # =====================================================
    # USEFUL COMMANDS
    # =====================================================

    if data == "commands":

        text = (
            "📋 Useful Commands\n\n"
            "`/pin 4h`\n"
            "`/pin 8h`\n"
            "`/pin 12h`\n"
            "`/pin 24h`\n\n"
            "Only the next eligible member message "
            "will be pinned."
        )

        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=back_button("home"),
        )

        return


# =========================================================
# BOT ADDED TO GROUP
# =========================================================

async def bot_added_to_group(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    chat_member = update.my_chat_member

    if not chat_member:
        return

    chat = update.effective_chat

    if not chat:
        return

    if chat.type not in (
        "group",
        "supergroup",
    ):
        return

    new_status = chat_member.new_chat_member.status

    if new_status not in (
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
    ):
        return

    actor = chat_member.from_user

    if not actor:
        return

    save_user(actor)

    # Only users with access can register groups.
    if not user_has_access(actor.id):
        return

    # Check bot permission if it is administrator.
    try:

        bot_member = await context.bot.get_chat_member(
            chat.id,
            context.bot.id,
        )

        if bot_member.status == ChatMemberStatus.ADMINISTRATOR:

            if not bot_member.can_pin_messages:

                return

    except Exception:
        pass

    add_group(
        chat.id,
        chat.title or "Unnamed Group",
        actor.id,
    )


# =========================================================
# /PIN
# =========================================================

async def pin_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    message = update.effective_message

    chat = update.effective_chat

    user = update.effective_user

    if not message or not chat:
        return

    if chat.type not in (
        "group",
        "supergroup",
    ):
        return

    if not user:
        return

    save_user(user)

    # -----------------------------------------------------
    # ACCESS CHECK
    # -----------------------------------------------------

    if not user_has_access(user.id):
        return

    # -----------------------------------------------------
    # CHECK GROUP
    # -----------------------------------------------------

    group = db.execute(
        """
        SELECT chat_id
        FROM groups
        WHERE chat_id = ?
        AND added_by = ?
        """,
        (
            chat.id,
            user.id,
        ),
    ).fetchone()

    if not group:

        await message.reply_text(
            "❌ This group is not added to your Pin Cycle."
        )

        return

    # -----------------------------------------------------
    # CHECK DURATION
    # -----------------------------------------------------

    if not context.args:

        await message.reply_text(
            "Usage:\n\n"
            "/pin 4h\n"
            "/pin 8h\n"
            "/pin 12h\n"
            "/pin 24h"
        )

        return

    duration = context.args[0].lower()

    allowed = {
        "4h": 4,
        "8h": 8,
        "12h": 12,
        "24h": 24,
    }

    if duration not in allowed:

        await message.reply_text(
            "❌ Invalid duration.\n\n"
            "Available:\n"
            "/pin 4h\n"
            "/pin 8h\n"
            "/pin 12h\n"
            "/pin 24h"
        )

        return

    hours = allowed[duration]

    # -----------------------------------------------------
    # SAVE PENDING PIN
    # -----------------------------------------------------

    db.execute(
        """
        INSERT INTO pending_pins
        (chat_id, hours, created_at)
        VALUES (?, ?, ?)

        ON CONFLICT(chat_id)
        DO UPDATE SET
            hours = excluded.hours,
            created_at = excluded.created_at
        """,
        (
            chat.id,
            hours,
            now(),
        ),
    )

    db.commit()

    # -----------------------------------------------------
    # ALERT
    # --------------------------------------------
