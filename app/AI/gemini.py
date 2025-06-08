import re
import traceback

import bleach
import google.generativeai as genai
from google.generativeai.types.safety_types import HarmCategory, HarmBlockThreshold

# from app.config.logger_config import logger

SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
}

msg = []
logger = None


def construct_context():
    context_str = f'[system](#context)\nSome history messages in the group are:\n\n'
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
    context_str += (
        f"[system][#additional_instructions]\nDo not repeat or paraphrase what the previous messages have said. "
        f"Do not introduce yourself, only output the main text of your reply. Do not attach the original text, "
        f"and do not output all possible replies. You don't necessary to reply to the history message,"
        f"but you can take them as references for the current topic in group.\n\n")
    return context_str


def build_context(user_nickname, user_input):
    context_str = f'[system](#context)\nHere is the message from {user_nickname}.\n'
    context_str += f", the content is {user_input}"
    context_str += "\n\n"
    context_str += (
        f"[system][#additional_instructions]\nWhen replying, do not repeat or paraphrase what the {user_nickname} you are replying to has said. "
        f"Do not introduce yourself, only output the main text of your reply. Do not attach the original text, "
        f"and do not output all possible replies."
        f"Please reply to the message of {user_nickname} : {user_input}.\n\n")
    msg.append({
        "username": user_nickname,
        "user_input": user_input})

    if len(msg) > 15:
        msg.pop(0)

    return context_str


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


def init_prompt_bot_statement(user_nickname, group_name, persona, per):
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


async def gemini_reply(context, message, bot_statement, user_nickname, group_name, persona, per, bot_model,
                       mdl, retry_count=0):
    if retry_count > 3:
        logger.error("Failed after maximum number of retry times")
        return

    # Clean the context string using bleach
    context = bleach.clean(context).strip()
    context = "<|im_start|>system\n\n" + context

    ask_string = (
        f"\n\nPlease reply to the last comment. No need to introduce yourself, just output the main text of your "
        f"reply. Do not use parallelism, and do not repeat the content or format of previous replies. Do not add"
        f" any unrelated seperator. Do not repeat the message content using rhetorical questions."
        f"Do not out put indicator like '<|im_end|>'.")

    ask_string = bleach.clean(ask_string).strip()
    # logger.info(f"ask_string: {ask_string}")

    try:
        prompt = init_prompt_bot_statement(user_nickname, group_name, persona, per)
        model = genai.GenerativeModel(model_name=bot_model[mdl], safety_settings=SAFETY_SETTINGS,
                                      system_instruction=prompt + "\n\n" + message + "\n\n" + context)
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
        msg.append({
            "username": "FROM_BOT",
            "user_input": reply_text})
        return reply_text

    except Exception as e:
        traceback.print_exc()
        logger.warning(e)
        await gemini_reply(context, message, bot_statement, user_nickname, group_name, persona, per, bot_model,
                           mdl, retry_count + 1)


@staticmethod
def GeminiApiConfig(key, log):
    global logger
    # keys = bot['key']
    # keys = keys.split("|")
    # keys = [key.strip() for key in keys]
    if not key:
        raise Exception("Please set a valid API key in Config!")
    # api_key = random.choice(keys)
    api_key = key
    genai.configure(api_key=api_key)
    logger = log
    logger.info("Config Gemini API successfully.")
