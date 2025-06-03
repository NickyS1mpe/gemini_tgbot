import asyncio
import random
import sys
import traceback

from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup)
from telegram.error import TelegramError
from telegram.ext import (Application, CommandHandler,
                          ContextTypes, MessageHandler, filters, ConversationHandler, CallbackQueryHandler)

from game.blackjack import (start, join, action_handler, bet_callback_handler, load_balances, add_balance)
from config.config import bot
from AI.gemini import (GeminiApiConfig, gemini_reply, construct_context, build_context)
from config.logger_config import logger, setup_logger, log_message

log = ''
bot_token = ''
admin = ''
key = ''
bot_nickname = []
groups = []
persona = []
bot_model = []

per = 0
mdl = 0

SPE = range(1)


def load_config():
    global log
    global bot_token
    global persona
    global key
    global admin
    global bot_nickname
    global groups
    global bot_model

    required_keys = ['log', 'bot_token', 'persona', 'key', 'admin', 'bot_nickname', 'groups', 'model']

    for key in required_keys:
        if key not in bot or not bot[key]:
            # logger.error(f"Missing or empty configuration key: {key}")
            raise ValueError(f"Missing or empty configuration key: {key}")

    log = bot['log']
    bot_token = bot['bot_token']
    persona = bot['persona']
    key = bot['key']
    admin = bot['admin']
    bot_nickname = bot['bot_nickname']
    groups = bot['groups']
    bot_model = bot['model']

    setup_logger(log)
    GeminiApiConfig(key, logger)
    load_balances(logger)

    logger.info("Loading config successfully.")


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in ["group", "supergroup"] and update.message:
        user_input = update.message.text
        chat_id = update.effective_chat.id
        reply_to_id = update.message.message_id
        user_nickname = (update.effective_user.first_name or "") + ' ' + (update.effective_user.last_name or "")
        # bot_nickname = context.bot.username or ""
        group_name = update.effective_chat.title or ""
        group_id = update.effective_chat.id
        is_reply_to_bot = False
        if update.message.reply_to_message:
            is_reply_to_bot = update.message.reply_to_message.from_user.id == context.bot.id

        if group_id in groups:
            try:
                if is_reply_to_bot or bot_nickname[per] in user_input:
                    # if update.message.reply_to_message:
                    #     reply_to_id = update.message.reply_to_message.message_id

                    logger.info(f"From user: {user_nickname} receive message: {user_input}")

                    ctr = construct_context()
                    message = build_context(user_nickname, user_input)

                    reply = await gemini_reply(
                        context=ctr,
                        message=message,
                        bot_statement="",
                        user_nickname=user_nickname,
                        group_name=group_name,
                        persona=persona,
                        per=per,
                        bot_model=bot_model,
                        mdl=mdl
                    )

                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=reply,
                        reply_to_message_id=reply_to_id
                    )
                elif random.randint(1, 30) == 3:
                    logger.info(f"From user: {user_nickname} receive message: {user_input}")

                    message = build_context(user_nickname, user_input)

                    reply = await gemini_reply(
                        context="",
                        message=message,
                        bot_statement="",
                        user_nickname=user_nickname,
                        group_name=group_name,
                        persona=persona,
                        per=per,
                        bot_model=bot_model,
                        mdl=mdl
                    )

                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=reply,
                        reply_to_message_id=reply_to_id
                    )
            except Exception as e:
                logger.warning(e)


async def persona_select_starter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in ["group", "supergroup"] and update.message:
        user = update.effective_user
        chat = update.effective_chat
        user_nickname = (update.effective_user.first_name or "") + ' ' + (update.effective_user.last_name or "")
        group_id = update.effective_chat.id

        if group_id in groups:
            log_message(user.username, chat.title if chat.title else chat.type, user.is_bot, 'command', '/select')

            keyboard = [
                [InlineKeyboardButton(p['t'], callback_data=str(index)) for index, p in enumerate(persona)]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                text=f"Please select a persona, or send /cancel to cancel request:",
                reply_markup=reply_markup
            )

            return SPE
    return ConversationHandler.END


async def selection_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    p = query.data
    global per
    per = int(p)

    logger.info(f"Persona was changed to type {p}")
    await query.edit_message_text(f"Persona was changed to type {persona[per]['t']}.")

    return ConversationHandler.END


async def persona_starter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    user_nickname = (update.effective_user.first_name or "") + ' ' + (update.effective_user.last_name or "")
    log_message(user.username, chat.title if chat.title else chat.type, user.is_bot, 'command', '/persona')

    if context.args:
        text = ' '.join(context.args)

        keyboard = [
            [
                InlineKeyboardButton("Approve", callback_data=f"approve:{chat.id}:{user.id}:{user_nickname}:{text}"),
                InlineKeyboardButton("Reject", callback_data=f"reject:{chat.id}:{user.id}:{user_nickname}:{text}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await context.bot.send_message(
            chat_id=admin,
            text=f"User @{user.username or user_nickname} submitted persona request:\n\n{text}",
            reply_markup=reply_markup
        )

        await update.message.reply_text(f"You set persona: {text}. Please wait for admin to approve.")
    else:
        await update.message.reply_text("Please provide text after /persona, e.g. /persona friendly AI assistant.")


async def approval_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action, chat_id, user_id, user_nickname, content = query.data.split(":", 4)

    if action == "approve":
        global persona
        persona = content
        logger.info(f"{user_nickname}'s submission was approved:\n\n{content}")

        await context.bot.send_message(chat_id=chat_id, text=f"{user_nickname}'s request was approved:\n\n{content}")
        await query.edit_message_text(f"Approved: {content}")

    elif action == "reject":
        logger.info(f"{user_nickname}'s submission was rejected:\n\n{content}")
        await context.bot.send_message(chat_id=chat_id, text=f"{user_nickname}'s request was rejected:\n\n{content}")
        await query.edit_message_text(f"Rejected: {content}")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels the current conversation for retrival and conversion."""
    user = update.effective_user
    chat = update.effective_chat
    log_message(user.username, chat.title if chat.title else chat.type, user.is_bot, 'command', '/cancel')

    await update.message.reply_text("Request cancel.")
    return ConversationHandler.END


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle bot errors and exceptions."""
    logger.critical("Error:", exc_info=context.error)

    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_str = ''.join(tb_list)

    message = (
        "*An unexpected error occurred.*\n"
        f"`{context.error}`\n\n"
        "*Traceback:*\n"
        f"```{tb_str[-1000:]}```"  # Last 1000 chars to avoid flooding
    )

    # Send error message to developer/admin
    await context.bot.send_message(
        chat_id=bot['admin'],
        text=message,
        parse_mode="Markdown"
    )

    if isinstance(update, Update) and update.effective_chat:
        try:
            user_id = update.effective_user.id
            chat_id = update.effective_chat.id

            await context.bot.send_message(
                chat_id=chat_id,
                text="Sorry, something went wrong. Please try again later."
            )
        except TelegramError as e:
            logger.warning(f"Failed to send error message to user: {e}")


async def stop_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != admin:
        await update.message.reply_text("You are not authorized.")
        return

    # await update.message.reply_text("Bot is shutting down...")
    await context.bot.send_message(
        chat_id=bot['admin'],
        text="Bot is shutting down...",
        parse_mode="Markdown"
    )

    async def delayed_shutdown():
        await context.application.stop()
        await context.application.shutdown()
        await asyncio.sleep(0.5)
        raise SystemExit(0)

    context.application.create_task(delayed_shutdown())


def main():
    try:
        load_config()
        logger.info("***** TELEGRAM BOT START *****")

        if not bot_token or bot_token == "YOUR_BOT_TOKEN":
            logger.error('Error: no bot token found. Please set up your bot token in config.')
            sys.exit(1)

        app = Application.builder().token(bot_token).build()
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

        persona_handler = ConversationHandler(
            entry_points=[CommandHandler("select", persona_select_starter)],
            states={
                SPE: [CallbackQueryHandler(selection_callback_handler)],
            },
            fallbacks=[CommandHandler("cancel", cancel)]
        )
        app.add_handler(persona_handler)
        # app.add_handler(CommandHandler("persona", persona_starter))
        # app.add_handler(CallbackQueryHandler(approval_callback_handler, pattern="^(approve|reject):"))

        # blackjack game handler
        app.add_handler(CommandHandler("blackjack", lambda u, c: start(u, c, groups=groups)))
        app.add_handler(CallbackQueryHandler(join, pattern="^join$"))
        app.add_handler(CallbackQueryHandler(action_handler, pattern="^(hit|stand)$"))
        app.add_handler(CallbackQueryHandler(bet_callback_handler, pattern=r"^(bet_|done$)"))
        app.add_handler(CommandHandler("add_balance", lambda u, c: add_balance(u, c, groups=groups)))

        app.add_error_handler(error_handler)
        app.add_handler(CommandHandler("stop_bot", stop_bot))

        logger.info("Start polling for updates...")
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

    except BaseException as e:
        logger.error(e)
    finally:
        # save_balances()
        logger.info("***** TELEGRAM BOT STOP *****")
        sys.exit()


if __name__ == '__main__':
    main()
