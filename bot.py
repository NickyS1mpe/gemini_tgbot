import random
import re
import sys
import google.generativeai as genai
from google.generativeai.types.safety_types import HarmCategory, HarmBlockThreshold
import bleach

from logger_config import logger, setup_logger, load_log_file
from config import bot
from telegram import (Update, InputFile, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, KeyboardButton,
                      ReplyKeyboardMarkup)
from telegram.ext import (Application, CommandHandler,
                          ContextTypes, MessageHandler, filters, ConversationHandler, CallbackQueryHandler)

res = []
msg = []

SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
}


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


def init_prompt_botstatement(user_nickname, bot_nickname, group_name):
    persona = None
    pre_reply = None

    if not persona:
        persona = bot["persona"]
        pre_reply = bot["pre_reply"]
    persona = persona.format(n=user_nickname, k=bot_nickname, m=group_name)
    pre_reply = pre_reply.format(n=user_nickname, k=bot_nickname, m=group_name)
    # logger.info("PERSONA:" + persona)
    return persona, pre_reply


async def sydney_reply(context, bot_statement, user_nickname, bot_nickname, group_name, retry_count=0):
    if retry_count > 3:
        logger.error("Failed after maximum number of retry times")
        return

    # Clean the context string using bleach
    context = bleach.clean(context).strip()
    context = "<|im_start|>system\n\n" + context

    ask_string = f"Please reply to the last comment. No need to introduce yourself, just output the main text of your reply. Do not use parallelism, and do not repeat the content or format of previous replies."

    ask_string = bleach.clean(ask_string).strip()
    # logger.info(f"ask_string: {ask_string}")

    try:
        persona, pre_reply = init_prompt_botstatement(user_nickname, bot_nickname, group_name)
        model = genai.GenerativeModel(model_name="gemini-1.5-flash-latest", safety_settings=SAFETY_SETTINGS,
                                      system_instruction=persona + "\n\n" + context)
        gemini_messages = ask_by_user(ask_string)
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
        return reply_text

    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.warning(e)
        await sydney_reply(context, bot_statement, user_nickname, bot_nickname, group_name, retry_count + 1)


@staticmethod
def GeminiApiConfig():
    keys = bot['key']
    keys = keys.split("|")
    keys = [key.strip() for key in keys]
    if not keys:
        raise Exception("Please set a valid API key in Config!")
    api_key = random.choice(keys)
    genai.configure(api_key=api_key)


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
    return context_str


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type in ["group", "supergroup"]:
        user_input = update.message.text
        chat_id = update.effective_chat.id
        reply_to_id = update.message.message_id
        user_nickname = (update.effective_user.first_name or "") + ' ' + (update.effective_user.last_name or "")
        bot_nickname = context.bot.username or ""
        group_name = update.effective_chat.title or ""
        group_id = update.effective_chat.id
        is_reply_to_bot = False
        if update.message.reply_to_message:
            is_reply_to_bot = update.message.reply_to_message.from_user.id == context.bot.id

        if group_id == -1002050374442 or group_id == -4166825212:
            if is_reply_to_bot or "糯糯" in user_input:
                # if update.message.reply_to_message:
                #     reply_to_id = update.message.reply_to_message.message_id

                logger.info(f"From user: {user_nickname} receive message: {user_input}")

                ctr = construct_context()
                ctr += build_context(user_nickname, user_input)
                msg.append({
                    "username": user_nickname,
                    "user_input": user_input})

                reply = await sydney_reply(
                    context=ctr,
                    bot_statement="",
                    user_nickname=user_nickname,
                    bot_nickname="糯糯",
                    group_name=group_name,
                )

                msg.append({
                    "username": "FROM_BOT",
                    "user_input": reply})
                if len(msg) > 15:
                    msg.pop()

                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=reply,
                    reply_to_message_id=reply_to_id
                )
            elif random.randint(1, 30) == 3:
                logger.info(f"From user: {user_nickname} receive message: {user_input}")

                build_context(user_nickname, user_input)

                reply = await sydney_reply(
                    context=user_input,
                    bot_statement="",
                    user_nickname=user_nickname,
                    bot_nickname="糯糯",
                    group_name=group_name,
                )

                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=reply,
                    reply_to_message_id=reply_to_id
                )


def main():
    try:
        setup_logger(bot['config'])
        GeminiApiConfig()

        logger.info("***** TELEGRAM BOT START *****")
        bot_token = bot['bot_token']

        if not bot_token or bot_token == "YOUR_BOT_TOKEN":
            logger.error('Error: no bot token found. Please set up your bot token in config.')
            sys.exit(1)

        app = Application.builder().token(bot_token).build()
        app.add_handler(MessageHandler(filters.ALL, message_handler))
        # app.add_error_handler(error_handler)

        logger.info("Start polling for updates...")
        app.run_polling(allowed_updates=Update.ALL_TYPES)

    except BaseException as e:
        logger.error(e)
    finally:

        logger.info("***** TELEGRAM BOT STOP *****")
        sys.exit()


if __name__ == '__main__':
    main()
