import random
import re
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
balances = {}


def load_balances(filename="balances.txt"):
    # global balances
    try:
        with open(filename, "r") as f:
            for line in f:
                user_id, amount = line.strip().split(":")
                if user_id == 'AI':
                    balances[user_id] = int(amount)
                else:
                    balances[int(user_id)] = int(amount)
        if 'AI' not in balances:
            balances['AI'] = 1000
    except FileNotFoundError:
        logger.error("Balance file not found")


def save_balances(filename="balances.txt"):
    with open(filename, "w") as f:
        for user_id, amount in balances.items():
            f.write(f"{user_id}:{amount}\n")


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


async def timeout_player(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    chat_id = data['chat_id']
    player_id = data['player_id']
    message_id = data['msg_id']
    game = games.get(chat_id)

    if not game or game['players'][game['current']] != player_id:
        return

    await context.bot.edit_message_text(chat_id=chat_id,
                                        message_id=message_id,
                                        text=(f"{game['names'][player_id]} did not respond in time.\n"
                                              f"Stands with: "
                                              f"{format_hand(game['hands'][player_id])} "
                                              f"(Total: {calculate_hand_value(game['hands'][player_id])})"),
                                        parse_mode='HTML')
    game['context'] += (f"{game['names'][player_id]} stands with: {format_hand(game['hands'][player_id])} "
                        f"(Total: {calculate_hand_value(game['hands'][player_id])})")
    game['context'] += '\n\n'
    game['current'] += 1
    await send_next_turn(context, chat_id, None)


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
    text = (f"<b>{game['names'][player_id]}</b>'s turn\nHand: {format_hand(hand)} (Total: {value})\n"
            f"You have 20 seconds to choose.")
    if message_id is None:
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=markup,
            parse_mode='HTML'
        )
        game['last_turn'] = msg.message_id
    else:
        msg = await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=markup,
            parse_mode='HTML'
        )
    job = context.job_queue.run_once(timeout_player, 20, chat_id=chat_id,
                                     data={'chat_id': chat_id, 'player_id': player_id, 'msg_id': msg.message_id})
    game['jobs'][player_id] = job


async def start_game(context: ContextTypes.DEFAULT_TYPE, chat_id):
    game = games[chat_id]

    if 'bet_message_id' in game and game['bet_message_id']:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=game['bet_message_id'])
        except Exception as e:
            logger.warning(f"Error deleting bet message: {e}.")

    deck = deck_template.copy()
    random.shuffle(deck)
    game['deck'] = deck

    for player_id in game['players']:
        game['hands'][player_id] = [deal_card(deck), deal_card(deck)]

    game['dealer'] = [deal_card(deck), deal_card(deck)]
    game['AI']['hands'] = [deal_card(deck), deal_card(deck)]
    game['current'] = 0

    dealer_hand = game['dealer']
    dealer_visible = dealer_hand[0]
    dealer_total = calculate_hand_value(dealer_hand)

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"Dealer's visible card: {dealer_visible}"
    )

    # if dealer_total == 21:
    #     await context.bot.send_message(
    #         chat_id=chat_id,
    #         text=(f"Dealer has Blackjack! {format_hand(dealer_hand)} (Total: 21)\nGame ends."
    #               f"Send /blackjack to start a new game. Send /add_balance to ask AI for points.")
    #     )
    #
    #     logger.info(f"Blackjack game ends in chat {chat_id}.")
    #     save_balances()
    #     del games[chat_id]
    #     return

    await send_next_turn(context, chat_id, None)


async def bet_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")
        return
    user_id = query.from_user.id
    chat_id = query.message.chat.id

    if chat_id not in games:
        return

    game = games.get(chat_id)
    if user_id not in game['players'] or user_id in game['betting_done']:
        return

    current_bet = game['bets'].get(user_id)
    # default balance 1000 if new user
    balance = balances.get(user_id, 1000) - current_bet
    # if user_id not in game['bets'] and balance < 50:
    #     current_bet = balance

    data = query.data
    if data.startswith("bet_"):
        if data == "bet_allin":
            bet_amount = balance + current_bet
        elif data in ["bet_2x", "bet_3x", "bet_5x"]:
            multiplier = int(data.split("_")[1][0])  # Extract 2, 3, or 5
            bet_amount = current_bet * multiplier
        else:
            bet_amount = int(data.split("_")[1])
            bet_amount += current_bet

        if bet_amount > balance + current_bet:
            # await query.answer("Sorry you have not enough balances", show_alert=True)
            bet_amount = balance + current_bet
            # return

        if bet_amount != game['bets'][user_id]:
            game['bets'][user_id] = bet_amount

            text = (f"20s to make you bet (default is 50). Current bets:\n\n"
                    f"Gemini has bet {game['AI']['bets']} (Balance: {balances.get('AI')})\n")

            for player_id in game['players']:
                text += (f"{game['names'][player_id]} has bet {game['bets'][player_id]} "
                         f"(Balance: {balances.get(player_id, 1000) - game['bets'][player_id]})\n")

            keyboard = [
                [InlineKeyboardButton("50", callback_data="bet_50"),
                 InlineKeyboardButton("100", callback_data="bet_100"),
                 InlineKeyboardButton("500", callback_data="bet_500")],
                [InlineKeyboardButton("2x", callback_data="bet_2x"),
                 InlineKeyboardButton("3x", callback_data="bet_3x"),
                 InlineKeyboardButton("5x", callback_data="bet_5x")],
                [InlineKeyboardButton("All In", callback_data="bet_allin")],
                # [InlineKeyboardButton("Done", callback_data="done")]
            ]

            await query.edit_message_text(
                text=text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    elif data == 'done':
        if user_id not in game['betting_done']:
            game['betting_done'].add(user_id)

        if len(game['betting_done']) == len(game['players']):
            # Deduct balances
            for pid, bet in game['bets'].items():
                balances[pid] = balances.get(pid, 1000) - bet
            # save_balances()

            # await start_game(context, chat_id)


async def betting_timeout(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    chat_id = data["chat_id"]

    if chat_id not in games:
        return

    game = games[chat_id]

    # Finalize betting for users who didn't press "Done"
    for pid in game['players']:
        if pid not in game['betting_done']:
            game['betting_done'].add(pid)

    # Deduct balances only once
    for pid, bet in game['bets'].items():
        if pid in game['players']:
            balances[pid] = balances.get(pid, 1000) - bet

    await start_game(context, chat_id)


# This is the async wrapper for JobQueue
async def send_bet(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    if chat_id not in games:
        return

    game = games.get(chat_id)

    if 'join_message_id' in game and game['join_message_id']:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=game['join_message_id'])
        except Exception as e:
            logger.warning(f"Error deleting join message: {e}.")

    keyboard = [
        [InlineKeyboardButton("50", callback_data="bet_50"),
         InlineKeyboardButton("100", callback_data="bet_100"),
         InlineKeyboardButton("500", callback_data="bet_500")],
        [InlineKeyboardButton("2x", callback_data="bet_2x"),
         InlineKeyboardButton("3x", callback_data="bet_3x"),
         InlineKeyboardButton("5x", callback_data="bet_5x")],
        [InlineKeyboardButton("All In", callback_data="bet_allin")],
        # [InlineKeyboardButton("Done", callback_data="done")]
    ]

    # load_balances()
    text = "20s to make you bet (default is 50). Current bets:\n\n"
    no_bal = []

    balance = balances['AI']
    if balance > 0:
        prompt = (
            f"You are a Blackjack master with a balance of {balance}. "
            f"Initial bet is 50 or all your balance if it is less than 50."
            "The betting options are any positive whole number which is divisible by 50, "
            "but don't bet more than your current balance. "
            "Decide how much you want to bet for this round. Respond only with the number of your bet. "
            "(e.g., 100, 200). Betting can be more aggressive."
        )
        reply = await gemini_blackjack(prompt, '')
        reply = reply.strip()
        bet = balance

        if re.fullmatch(r"\d+", reply):
            bet = int(reply)

        # balances['AI'] = balance - bet
        game['AI']['name'] = 'Gemini'
        game['AI']['bets'] = bet
        balances['AI'] -= bet

        text += (f"Gemini has bet {game['AI']['bets']} "
                 f"(Balance: {balances['AI']})\n")

    else:
        text += f"Gemini has lost all its points so that he cannot play with you.\n"

    # initial bet
    for player_id in game['players']:
        # game['bets'][player_id] = 50  # Default bet
        current_bet = game['bets'].get(player_id, 50)
        # default balance 1000 if new user
        balance = balances.get(player_id, 1000)
        if player_id not in game['bets'] and balance < 50:
            current_bet = balance
        game['bets'][player_id] = current_bet

        if current_bet == 0:
            text += f"{game['names'][player_id]} has no balance left. Will be kicked out.\n"
            no_bal.append(player_id)
        else:
            text += (f"{game['names'][player_id]} has bet {game['bets'][player_id]} "
                     f"(Balance: {balance - game['bets'][player_id]})\n")

    for p in no_bal:
        game['players'].remove(p)

    message = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    game['bet_message_id'] = message.message_id
    # await bet_callback_handler(context, chat_id)
    context.job_queue.run_once(betting_timeout, when=20, data={"chat_id": chat_id})


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE, groups=None):
    chat_id = update.effective_chat.id
    if chat_id in groups and chat_id not in games:
        logger.info(f"New blackjack game starts in chat {chat_id}.")
        games[chat_id] = {
            'players': [],
            'names': {},
            'hands': {},
            'dealer': [],
            'join_message_id': None,
            'bet_message_id': None,
            'last_turn': None,
            'context': "Current player's cards and total:\n\n",
            'jobs': {},
            'bets': {},
            'betting_done': set(),
            'AI': {}
        }
        join_button = [[InlineKeyboardButton("Join", callback_data="join")]]
        msg = await update.message.reply_text(
            "Blackjack game starting in 20 seconds! Press Join:",
            reply_markup=InlineKeyboardMarkup(join_button)
        )
        games[chat_id]['join_message_id'] = msg.message_id
        context.job_queue.run_once(send_bet, 20, chat_id=chat_id)
    else:
        return


async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    # await query.answer()
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")
        return
    user = query.from_user
    chat_id = query.message.chat.id
    user_nickname = (update.effective_user.first_name or "") + ' ' + (update.effective_user.last_name or "")

    game = games.get(chat_id)
    if not games or not game:
        return

    if user.id not in game['players']:
        game['players'].append(user.id)
        game['names'][user.id] = user_nickname
        ctx = 'Blackjack game starting in 20 seconds!\n'
        for player in game['players']:
            ctx += f"{game['names'][player]} joined the game.\n"
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

    job = game['jobs'].pop(player_id, None)
    if job:
        job.schedule_removal()

    if query.data == "hit":
        card = deal_card(game['deck'])
        game['hands'][player_id].append(card)
        total = calculate_hand_value(game['hands'][player_id])
        if total > 21:
            text = (f"{game['names'][player_id]} busted with: "
                    f"{format_hand(game['hands'][player_id])} (Total: {total})")
            await query.edit_message_text(text)
            game['context'] += text
            game['context'] += '\n\n'
            game['current'] += 1
            await send_next_turn(context, chat_id, None)
        else:
            await send_next_turn(context, chat_id, game['last_turn'])

    elif query.data == "stand":
        text = (f"{game['names'][player_id]} stands with: {format_hand(game['hands'][player_id])} "
                f"(Total: {calculate_hand_value(game['hands'][player_id])})")
        await query.edit_message_text(text)
        game['context'] += text
        game['context'] += '\n\n'
        game['current'] += 1
        await send_next_turn(context, chat_id, None)


async def finish_game(context: ContextTypes.DEFAULT_TYPE, chat_id):
    game = games[chat_id]

    gemini = game['AI']['hands']
    gemini_context = (f"Your current cards: {format_hand(gemini)} "
                      f"(Total: {calculate_hand_value(gemini)})")
    gemini_context += '\n\n'

    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"<b>Gemini</b>'s turn\nHand: {format_hand(gemini)} (Total: {calculate_hand_value(gemini)})\n",
        parse_mode='HTML'
    )
    msg_id = msg.message_id

    while True:
        prompt = ('You are a Blackjack master. '
                  'Given a hand of cards, your only task is to decide whether to "hit" or '
                  '"stand" based on standard Blackjack strategy. Must only reply with a single word: either "hit" or '
                  '"stand".Do not explain your reasoning or include any other text. '
                  '\nExample input: "Hand: 9♠ 7♦ (Total: 16), '
                  'Dealer shows: 10♥" \nExpected output: hit\n\n')
        reply = await gemini_blackjack(prompt, game['context'] + gemini_context, 0)
        if 'hit' in reply:
            gemini.append(deal_card(game['deck']))
            await context.bot.edit_message_text(
                text=f"<b>Gemini</b>'s turn\nHand: {format_hand(gemini)} (Total: {calculate_hand_value(gemini)})\n",
                message_id=msg_id,
                chat_id=chat_id,
                parse_mode='HTML'
            )
            if calculate_hand_value(gemini) > 21:
                await context.bot.edit_message_text(
                    text=(f"Gemini busted with: "
                          f"{format_hand(gemini)} (Total: {calculate_hand_value(gemini)})"),
                    message_id=msg_id,
                    chat_id=chat_id,
                    parse_mode='HTML'
                )
                break
            gemini_context = (f"Your current cards: {format_hand(gemini)} "
                              f"(Total: {calculate_hand_value(gemini)})")
            gemini_context += '\n\n'
        else:
            await context.bot.edit_message_text(
                text=(f"Gemini stands with: {format_hand(gemini)} "
                      f"(Total: {calculate_hand_value(gemini)})"),
                message_id=msg_id,
                chat_id=chat_id,
                parse_mode='HTML'
            )
            break

    dealer = game['dealer']
    while calculate_hand_value(dealer) < 17:
        dealer.append(deal_card(game['deck']))
    dealer_total = calculate_hand_value(dealer)

    result = f"Dealer hand: {format_hand(dealer)} (Total: {dealer_total})\n\n"
    gemini_total = calculate_hand_value(gemini)
    gemini_bet = game['AI']['bets']
    if gemini_total > 21:
        result += f"<b>Gemini</b> busted."
    elif dealer_total > 21 or gemini_total > dealer_total:
        result += f"<b>Gemini</b> wins!"
        balances['AI'] = balances['AI'] + 2 * gemini_bet  # Win: get back bet + win amount
    elif gemini_total == dealer_total:
        result += f"<b>Gemini</b> ties."
        balances['AI'] = balances['AI'] + gemini_bet  # Tie: get back bet
    else:
        result += f"<b>Gemini</b> loses."

    result += f" Bet: {gemini_bet}, New Balance: {balances['AI']}\n\n"

    for pid in game['players']:
        player_total = calculate_hand_value(game['hands'][pid])
        name = game['names'][pid]
        bet = game['bets'].get(pid, 50)

        if player_total > 21:
            result += f"<b>{name}</b> busted."
        elif dealer_total > 21 or player_total > dealer_total:
            result += f"<b>{name}</b> wins!"
            balances[pid] = balances.get(pid, 1000) + 2 * bet  # Win: get back bet + win amount
        elif player_total == dealer_total:
            result += f"<b>{name}</b> ties."
            balances[pid] = balances.get(pid, 1000) + bet  # Tie: get back bet
        else:
            result += f"<b>{name}</b> loses."

        result += f" Bet: {bet}, New Balance: {balances[pid]}\n\n"

    result += "Game ends. Send /blackjack to start a new game. Send /add_balance to ask AI for points."
    logger.info(f"Blackjack game ends in chat {chat_id}.")
    save_balances()
    await context.bot.send_message(
        chat_id=chat_id,
        text=result,
        parse_mode='HTML')
    del games[chat_id]


async def add_balance(update: Update, context: ContextTypes.DEFAULT_TYPE, groups=None):
    chat = update.effective_chat
    user = update.effective_user
    chat_id = chat.id
    user_id = user.id
    if chat_id in groups:
        user_nickname = (update.effective_user.first_name or "") + ' ' + (update.effective_user.last_name or "")
        if user_id in balances:
            balance = balances.get(user_id)
            if balance == 0:
                prompt = (
                    f"You are a blackjack game assistant. A player named {user_nickname} currently has a balance of 0. "
                    f"Please decide a fair amount of in-game currency to give them so they can continue playing. "
                    f"The amount should be reasonable for someone restarting the game.\n\n"
                    f"Only respond with the number (e.g., 100, 200). The amount can be more aggressive."
                )
                context_text = (
                    f"Player: {user_nickname}\n"
                    f"Current balance: 0\n"
                )
                reply = await gemini_blackjack(prompt, context_text)
                reply = reply.strip()

                if re.fullmatch(r"\d+", reply):
                    new_balance = int(reply)
                    balances[user_id] = new_balance
                    await update.message.reply_text(
                        f"{user_nickname}, you’ve been given {new_balance} points by Gemini to continue playing!")
                else:
                    await update.message.reply_text(f"Invalid response from AI. Please try again later.")
            elif balance > 0:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"{user_nickname}, you still have {balances.get(user_id)} left.",
                )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"{user_nickname}, you haven't played yet. Each new player receives a starting balance of 1000."
            )

    return


async def gemini_blackjack(prompt, context, retry_count=0):
    if retry_count > 3:
        logger.error("Failed after maximum number of retry times")
        return

    context = bleach.clean(context).strip()
    context = "<|im_start|>system\n\n" + context

    try:
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
