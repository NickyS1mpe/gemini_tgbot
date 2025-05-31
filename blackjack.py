import random
import traceback

import bleach
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (ApplicationBuilder, CommandHandler, CallbackQueryHandler,
                          ContextTypes, JobQueue)
from logger_config import logger
import google.generativeai as genai

SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
}

# Game state storage
games = {}

suits = ['♠', '♥', '♦', '♣']
ranks = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
deck_template = [f"{rank}{suit}" for suit in suits for rank in ranks]


def deal_card(deck):
    return deck.pop()


def get_card_value(card):
    rank = card[:-1]
    if rank in ['J', 'Q', 'K']:
        return 10
    elif rank == 'A':
        return 11
    else:
        return int(rank)


def calculate_hand_value(hand):
    value = sum(get_card_value(card) for card in hand)
    aces = sum(1 for card in hand if card.startswith('A'))
    while value > 21 and aces:
        value -= 10
        aces -= 1
    return value


def format_hand(hand):
    return ' '.join(hand)


async def send_next_turn(context: ContextTypes.DEFAULT_TYPE, chat_id, message_id):
    game = games[chat_id]
    if game['current'] >= len(game['players']):
        await finish_game(context, chat_id)
        return

    player_id = game['players'][game['current']]
    hand = game['hands'][player_id]
    value = calculate_hand_value(hand)
    keyboard = [
        [
            InlineKeyboardButton("Hit", callback_data="hit"),
            InlineKeyboardButton("Stand", callback_data="stand")
        ]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    if message_id is None:
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=f"<b>{game['names'][player_id]}</b>'s turn\nHand: {format_hand(hand)} (Total: {value})",
            reply_markup=markup,
            parse_mode='HTML'
        )
        game['last_turn'] = msg.message_id
    else:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=f"<b>{game['names'][player_id]}</b>'s turn\nHand: {format_hand(hand)} (Total: {value})",
            reply_markup=markup,
            parse_mode='HTML'
        )


async def start_game(context: ContextTypes.DEFAULT_TYPE, chat_id):
    game = games[chat_id]

    if 'join_message_id' in game and game['join_message_id']:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=game['join_message_id'])
        except Exception as e:
            logger.warning(f"Error: {e}")

    deck = deck_template.copy()
    random.shuffle(deck)
    game['deck'] = deck

    for player_id in game['players']:
        game['hands'][player_id] = [deal_card(deck), deal_card(deck)]

    game['dealer'] = [deal_card(deck), deal_card(deck)]
    game['current'] = 0

    await send_next_turn(context, chat_id, None)


# This is the async wrapper for JobQueue
async def schedule_start_game(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    await start_game(context, chat_id)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    games[chat_id] = {
        'players': [],
        'names': {},
        'hands': {},
        'dealer': [],
        'join_message_id': None,
        'last_turn': None,
        'context': "Current player's cards and total:\n\n"
    }
    join_button = [[InlineKeyboardButton("Join", callback_data="join")]]
    msg = await update.message.reply_text(
        "Blackjack game starting in 30 seconds! Press Join:",
        reply_markup=InlineKeyboardMarkup(join_button)
    )
    games[chat_id]['join_message_id'] = msg.message_id
    context.job_queue.run_once(schedule_start_game, 30, chat_id=chat_id)


async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    chat_id = query.message.chat.id
    user_nickname = (update.effective_user.first_name or "") + ' ' + (update.effective_user.last_name or "")

    game = games.get(chat_id)
    if user.id not in game['players']:
        game['players'].append(user.id)
        game['names'][user.id] = user_nickname
        ctx = ''
        for player in game['players']:
            ctx += f"Player {game['names'][player]} joined the game.\n"
        await query.edit_message_text(
            text=ctx,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Join", callback_data="join")]]
            )
        )


async def action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    if chat_id not in games:
        return
    game = games[chat_id]
    player_id = game['players'][game['current']]

    if query.from_user.id != player_id:
        # await query.message.reply_text("It's not your turn!")
        return

    if query.data == "hit":
        card = deal_card(game['deck'])
        game['hands'][player_id].append(card)
        total = calculate_hand_value(game['hands'][player_id])
        if total > 21:
            await query.edit_message_text(
                f"Player {game['names'][player_id]} busted with: {format_hand(game['hands'][player_id])} (Total: {total})")
            game['context'] += (f"Player {game['names'][player_id]} busted with: "
                                f"{format_hand(game['hands'][player_id])} (Total: {total})")
            game['context'] += '\n\n'
            game['current'] += 1
            await send_next_turn(context, chat_id, None)
        else:
            await send_next_turn(context, chat_id, game['last_turn'])

    elif query.data == "stand":
        await query.edit_message_text(
            f"Player {game['names'][player_id]} stands with: {format_hand(game['hands'][player_id])} "
            f"(Total: {calculate_hand_value(game['hands'][player_id])})")
        game['context'] += (f"Player {game['names'][player_id]} stands with: {format_hand(game['hands'][player_id])} "
                            f"(Total: {calculate_hand_value(game['hands'][player_id])})")
        game['context'] += '\n\n'
        game['current'] += 1
        await send_next_turn(context, chat_id, None)


async def finish_game(context: ContextTypes.DEFAULT_TYPE, chat_id):
    game = games[chat_id]
    dealer = game['dealer']
    dealer_context = (f"Your current cards: {format_hand(dealer)} "
                      f"(Total: {calculate_hand_value(dealer)})")
    dealer_context += '\n\n'
    # while calculate_hand_value(dealer) < 17:
    #     dealer.append(deal_card(game['deck']))
    while True:
        reply = await gemini_blackjack(game['context'] + dealer_context, 0)
        if 'hit' in reply:
            dealer.append(deal_card(game['deck']))
            if calculate_hand_value(dealer) > 21:
                break
            dealer_context = (f"Your current cards: {format_hand(dealer)} "
                              f"(Total: {calculate_hand_value(dealer)})")
            dealer_context += '\n\n'
        else:
            break

    dealer_total = calculate_hand_value(dealer)
    result = f"Gemini's hand: {format_hand(dealer)} (Total: {dealer_total})\n\n"
    for pid in game['players']:
        player_total = calculate_hand_value(game['hands'][pid])
        name = game['names'][pid]
        if player_total > 21:
            result += f"{name} busted.\n"
        elif dealer_total > 21 or player_total > dealer_total:
            result += f"{name} wins!\n"
        elif player_total == dealer_total:
            result += f"{name} ties.\n"
        else:
            result += f"{name} loses.\n"

    await context.bot.send_message(chat_id=chat_id, text=result)
    del games[chat_id]


async def gemini_blackjack(context, retry_count=0):
    if retry_count > 3:
        logger.error("Failed after maximum number of retry times")
        return

    context = bleach.clean(context).strip()
    context = "<|im_start|>system\n\n" + context

    try:
        prompt = ('You are a Blackjack master. Given a hand of cards, your only task is to decide whether to "hit" or '
                  '"stand" based on standard Blackjack strategy. Must only reply with a single word: either "hit" or '
                  '"stand".Do not explain your reasoning or include any other text. '
                  '\nExample input: "Hand: 9♠ 7♦ (Total: 16), '
                  'Dealer shows: 10♥" \nExpected output: hit\n\n')

        model = genai.GenerativeModel(model_name="gemini-1.5-flash-latest", safety_settings=SAFETY_SETTINGS,
                                      system_instruction=prompt)
        gemini_messages = [{
            "role": "user",
            "parts": [{"text": context}]
        }]
        response = model.generate_content(gemini_messages)
        reply_text = response.text
        logger.info(reply_text)

        return reply_text

    except Exception as e:
        traceback.print_exc()
        logger.warning(e)
        await gemini_blackjack(context, retry_count + 1)

# Main setup
# def main():
# app.add_handler(CommandHandler("blackjack", start))
# app.add_handler(CallbackQueryHandler(join, pattern="^join$"))
# app.add_handler(CallbackQueryHandler(action_handler, pattern="^(hit|stand)$"))
# app.run_polling()


# if __name__ == '__main__':
#     main()
