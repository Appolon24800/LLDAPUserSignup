"""Telegram command and callback handlers."""

from __future__ import annotations

import functools
import logging
from datetime import UTC, datetime

from telegram import Update
from telegram.ext import ContextTypes

from .auth import NOT_AUTHORIZED_MESSAGE, SLOW_DOWN_MESSAGE, is_admin
from .backend_client import BackendClient, BackendError
from .parsing import parse_group_args, parse_revoke_arg, split_command
from .picker import PickerState, apply_callback, build_keyboard, parse_callback, picker_text

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "Signup admin bot — commands:\n"
    "/gen [groups] — create a registration code (group picker when omitted)\n"
    "/list — show active codes\n"
    "/revoke <code> — invalidate a code\n"
    "/help — this message"
)


def admin_only(handler):
    """Allow-list + per-user throttle; non-admins get one generic reply."""

    @functools.wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if user is None or not is_admin(user.id, context.bot_data["admin_ids"]):
            if update.effective_message:
                await update.effective_message.reply_text(NOT_AUTHORIZED_MESSAGE)
            return
        if not context.bot_data["rate_limiter"].allow(user.id):
            await update.effective_message.reply_text(SLOW_DOWN_MESSAGE)
            return
        return await handler(update, context)

    return wrapper


def _backend(context: ContextTypes.DEFAULT_TYPE) -> BackendClient:
    return context.bot_data["backend"]


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(HELP_TEXT)


@admin_only
async def cmd_gen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start code generation: with args (validated) or the group picker."""
    _, args_text = split_command(update.effective_message.text)
    args = parse_group_args(args_text)

    try:
        available = await _backend(context).list_groups()
    except BackendError as err:
        await update.effective_message.reply_text(f"⚠️ Cannot reach the directory: {err}")
        return

    if not available:
        await update.effective_message.reply_text("⚠️ No groups found in LLDAP.")
        return

    unknown = [g for g in args if g not in set(available)]
    if unknown:
        await update.effective_message.reply_text(
            "⚠️ Unknown groups: " + ", ".join(unknown)
            + "\nUse the picker to choose existing groups."
        )
        args = []

    state = PickerState.create(available, preselected=args or None)
    context.user_data["picker"] = state
    await update.effective_message.reply_text(
        picker_text(state), reply_markup=build_keyboard(state)
    )


@admin_only
async def on_picker_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the inline keyboard of the /gen picker."""
    query = update.callback_query
    await query.answer()
    parsed = parse_callback(query.data)
    if parsed is None:
        return

    state: PickerState | None = context.user_data.get("picker")
    if state is None:
        await query.edit_message_text("⚠️ Picker expired — send /gen again.")
        return

    action = apply_callback(state, parsed)
    if action == "updated":
        await query.edit_message_text(
            picker_text(state), reply_markup=build_keyboard(state)
        )
        return
    if action == "cancel":
        context.user_data.pop("picker", None)
        await query.edit_message_text("❌ Cancelled.")
        return

    # confirm
    if not state.can_confirm:
        await query.edit_message_text(
            "⚠️ Select at least one group.", reply_markup=build_keyboard(state)
        )
        return
    user = update.effective_user
    try:
        result = await _backend(context).create_code(
            sorted(state.selected), created_by=str(user.id)
        )
    except BackendError as err:
        context.user_data.pop("picker", None)
        await query.edit_message_text(f"⚠️ Could not create the code: {err}")
        return
    context.user_data.pop("picker", None)
    await query.edit_message_text(_code_message(result))


def _code_message(result: dict) -> str:
    expires = _relative_expiry(result.get("expires_at", ""))
    lines = [
        "✅ Registration code created",
        "",
        f"`{result['code']}`",
        "",
        f"Link: {result['url']}",
        f"Groups: {', '.join(result.get('groups', []))}",
    ]
    if expires:
        lines.append(f"Expires: {expires}")
    lines += ["", "Single use only. Forward the link to the new user."]
    return "\n".join(lines)


def _relative_expiry(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        when = datetime.fromisoformat(iso)
    except ValueError:
        return ""
    delta = when - datetime.now(UTC)
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return "less than a minute"
    if minutes < 60:
        return f"in {minutes} min"
    return f"in {minutes // 60} h {minutes % 60} min"


@admin_only
async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        codes = await _backend(context).list_codes()
    except BackendError as err:
        await update.effective_message.reply_text(f"⚠️ {err}")
        return
    if not codes:
        await update.effective_message.reply_text("No active codes.")
        return
    lines = ["Active registration codes:", ""]
    for c in codes:
        groups = ", ".join(c.get("groups", []))
        expires = _relative_expiry(c.get("expires_at"))
        expiry_text = f"expires {expires}" if expires else "no expiry"
        failed = c.get("failed_attempts", 0)
        lines.append(f"• `{c['code_hint']}` — {groups} ({expiry_text}, {failed} failed)")
    await update.effective_message.reply_text("\n".join(lines))


@admin_only
async def cmd_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _, args_text = split_command(update.effective_message.text or "")
    code = parse_revoke_arg(args_text)
    if not code:
        await update.effective_message.reply_text("Usage: /revoke <code>")
        return
    try:
        revoked = await _backend(context).revoke_code(code)
    except BackendError as err:
        await update.effective_message.reply_text(f"⚠️ {err}")
        return
    if revoked:
        await update.effective_message.reply_text("✅ Code revoked.")
    else:
        await update.effective_message.reply_text("⚠️ Code not found (or already used/revoked).")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Last-resort handler: log and tell the user something generic."""
    logger.exception("Unhandled bot error", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("⚠️ Something went wrong. Please try again.")
