import random
import re
import sys
import traceback

import google.generativeai as genai
from google.generativeai.types.safety_types import HarmCategory, HarmBlockThreshold
import bleach
from telegram.error import TelegramError

from logger_config import logger, setup_logger, load_log_file, log_message
from config import bot
from telegram import (Update, InputFile, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, KeyboardButton,
                      ReplyKeyboardMarkup)
from telegram.ext import (Application, CommandHandler,
                          ContextTypes, MessageHandler, filters, ConversationHandler, CallbackQueryHandler)
from blackjack import (start, join, action_handler)

res = []
msg = []

SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
}

config = ''
bot_token = ''
persona = []
key = ''
admin = ''
bot_nickname = []
groups = []
bot_model = []
per = 0
mdl = 0

SPE = range(1)


def load_config():
    global config
    global bot_token
    global persona
    global key
    global admin
    global bot_nickname
    global groups
    global bot_model

    required_keys = ['config', 'bot_token', 'persona', 'key', 'admin', 'bot_nickname', 'groups', 'model']

    for key in required_keys:
        if key not in bot or not bot[key]:
            # logger.error(f"Missing or empty configuration key: {key}")
            raise ValueError(f"Missing or empty configuration key: {key}")

    config = bot['config']
    bot_token = bot['bot_token']
    persona = bot['persona']
    key = bot['key']
    admin = bot['admin']
    bot_nickname = bot['bot_nickname']
    groups = bot['groups']
    bot_model = bot['model']

    setup_logger(config)
    GeminiApiConfig()

    logger.info("Loading config successfully.")


def build_submission_context(name, context, group_name):
    context_str = f'[system](#context)\n以下是{""} : {name} 在群名称为{group_name}中发的言论。\n'
    if context != "":
        context_str += f"，内容是“{context[:3000]}”"
    context_str += "\n\n"
    context_str += f"[system][#additional_instructions]\nWhen replying, instead of repeating or imitating what the {name} you are replying to said, you reply with your own creativity. Needn't introduce yourself. Only output the body of your reply. Do not attach the original text, do not output all possible replies."
    return context_str


def remove_extra_format(reply: str) -> str:
    pattern = r'reply[^：]*：(.*)'
    result = re.search(pattern, reply, re.S)
    if result is None:
        return reply
    result = result.group(1).strip()
    if result.startswith("“") and result.endswith("”"):
        result = result[1:-1]
    return result


def ask_by_user(ask_string):
    # global res
    res = []
    res.append({
        "role": "user",
        "parts": [{"text": ask_string}]
    })
    # if len(res) > 15:
    #     res.pop(0)
    return res


def init_prompt_bot_statement(user_nickname, group_name):
    # persona = None
    # pre_reply = None
    #
    # if not persona:
    #     persona = bot["persona"]
    #     pre_reply = bot["pre_reply"]
    prompt = persona[per]['p'].format(n=user_nickname, k=persona[per]['n'], m=group_name)
    # pre_reply = pre_reply.format(n=user_nickname, k=bot_nickname, m=group_name)
    # logger.info("PERSONA:" + persona)
    return prompt


async def gemini_reply(context, message, bot_statement, user_nickname, group_name, retry_count=0):
    global bot_model
    if retry_count > 3:
        logger.error("Failed after maximum number of retry times")
        return

    # Clean the context string using bleach
    context = bleach.clean(context).strip()
    context = "<|im_start|>system\n\n" + context

    ask_string = (
        f"\n\nPlease reply to the last comment. No need to introduce yourself, just output the main text of your "
        f"reply. Do not use parallelism, and do not repeat the content or format of previous replies.")

    ask_string = bleach.clean(ask_string).strip()
    # logger.info(f"ask_string: {ask_string}")

    try:
        prompt = init_prompt_bot_statement(user_nickname, group_name)
        model = genai.GenerativeModel(model_name=bot_model[mdl], safety_settings=SAFETY_SETTINGS,
                                      system_instruction=prompt + "\n\n" + context)
        gemini_messages = ask_by_user(message + "\n\n" + ask_string)
        response = model.generate_content(gemini_messages)
        reply_text = response.text
        logger.info(reply_text)
        # print(reply_text)
        if "I am an automated reply bot" not in reply_text:
            reply_text += bot_statement
        # content.reply(reply_text)
        # res.append({
        #     "role": "model",
        #     "parts": [{"text": reply_text}]
        # })
        msg.append({
            "username": "FROM_BOT",
            "user_input": reply_text})
        return reply_text

    except Exception as e:
        traceback.print_exc()
        logger.warning(e)
        await gemini_reply(context, message, bot_statement, user_nickname, group_name, retry_count + 1)


@staticmethod
def GeminiApiConfig():
    # keys = bot['key']
    # keys = keys.split("|")
    # keys = [key.strip() for key in keys]
    if not key:
        raise Exception("Please set a valid API key in Config!")
    # api_key = random.choice(keys)
    api_key = key
    genai.configure(api_key=api_key)
    logger.info("Config Gemini API successfully.")


def construct_context():
    context_str = f'[system](#context)\nThe current messages in the group are:\n\n'
    for m in msg:
        if m['username'] == "FROM_BOT":
            context = f"You replied {m['user_input'][:10000]}"
            context += "\n"
        else:
            context = f"User {m['username']} sent a message"
            if m['user_input'] != "":
                context += f", the content is {m['user_input'][:10000]}"
            context += "\n"
        context_str += context
    return context_str


def build_context(user_nickname, user_input):
    context_str = f'[system](#context)\nHere is the message from {user_nickname}.\n'
    context_str += "\n"
    context_str += "\n\n"
    context_str += (
        f"[system][#additional_instructions]\nWhen replying, do not repeat or paraphrase what the {user_nickname} you are replying to has said. "
        f"Do not introduce yourself, only output the main text of your reply. Do not attach the original text, and do not output all possible replies. "
        f"Do not reply to the post itself, but to the last message of {user_nickname} : {user_input}.")
    msg.append({
        "username": user_nickname,
        "user_input": user_input})
    return context_str


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
                    )

                    if len(msg) > 15:
                        msg.pop()

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
                        # bot_nickname="糯糯",
                        group_name=group_name,
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
        app.add_handler(CommandHandler("blackjack", start))
        app.add_handler(CallbackQueryHandler(join, pattern="^join$"))
        app.add_handler(CallbackQueryHandler(action_handler, pattern="^(hit|stand)$"))

        app.add_error_handler(error_handler)

        logger.info("Start polling for updates...")
        app.run_polling(allowed_updates=Update.ALL_TYPES)

    except BaseException as e:
        logger.error(e)
    finally:
        logger.info("***** TELEGRAM BOT STOP *****")
        sys.exit()


if __name__ == '__main__':
    main()
