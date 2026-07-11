import asyncio
import logging

from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

import bd
from config import AVAILABLE_LEAGUES, BOT_TOKEN, MatchEvent
from parcing import ParcingSoccer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

POLL_INTERVAL = 10

if not BOT_TOKEN:
	raise RuntimeError("Установите переменную окружения BOT_TOKEN")

bot = AsyncTeleBot(BOT_TOKEN)
monitor = ParcingSoccer()


def build_league_keyboard(selected_leagues: list[str]) -> InlineKeyboardMarkup:
	markup = InlineKeyboardMarkup(row_width=2)
	buttons = []
	for league in AVAILABLE_LEAGUES:
		prefix = "✅ " if league in selected_leagues else ""
		button = InlineKeyboardButton(
			f"{prefix}{league}",
			callback_data=f"league_{league}",
		)
		buttons.append(button)
	markup.add(*buttons)
	return markup


async def send_event(chat_id: int, event: MatchEvent):
	if event.type == 'goal':
		await bot.send_message(chat_id, event.text)
		return

	if event.type == 'update':
		message_id = bd.get_match_message_id(chat_id, event.match_title)
		if message_id:
			try:
				await bot.edit_message_text(event.text, chat_id, message_id)
				return
			except Exception as exc:
				if 'message is not modified' in str(exc).lower():
					return
				logger.warning("Не удалось отредактировать сообщение: %s", exc)

		msg = await bot.send_message(chat_id, event.text)
		bd.save_match_message(chat_id, event.match_title, msg.message_id)
		return

	if event.type == 'finished':
		message_id = bd.get_match_message_id(chat_id, event.match_title)
		if message_id:
			try:
				await bot.edit_message_text(event.text, chat_id, message_id)
			except Exception:
				await bot.send_message(chat_id, event.text)
		else:
			await bot.send_message(chat_id, event.text)
		bd.delete_match_message(chat_id, event.match_title)


async def broadcast_event(event: MatchEvent, subscriptions: dict[int, list[str]]):
	if not event.league:
		return

	tasks = [
		send_event(user_id, event)
		for user_id, leagues in subscriptions.items()
		if event.league in leagues
	]
	if tasks:
		await asyncio.gather(*tasks, return_exceptions=True)


async def monitor_matches():
	logger.info("Фоновый мониторинг матчей запущен")

	while True:
		try:
			subscriptions = bd.get_all_subscriptions()
			if not subscriptions:
				await asyncio.sleep(POLL_INTERVAL)
				continue

			events = await asyncio.to_thread(monitor.poll_once, POLL_INTERVAL)
			for event in events:
				await broadcast_event(event, subscriptions)

		except Exception:
			logger.exception("Ошибка в фоновом мониторинге")

		await asyncio.sleep(POLL_INTERVAL)


@bot.message_handler(commands=['help', 'start'])
async def send_welcome(message):
	text = (
		"Привет, я Matchbot.\n"
		"Я уведомлю тебя, если матч начнётся или кто-нибудь забьёт гол!\n\n"
		"Команды:\n"
		"/match — выбрать лиги для отслеживания\n"
		"/leagues — показать выбранные лиги\n"
		"/matching — статус мониторинга\n\n"
		"После выбора лиг уведомления приходят автоматически."
	)
	await bot.send_message(message.chat.id, text)


@bot.message_handler(commands=['match'])
async def choose_leagues(message):
	try:
		bd.ensure_user(message.chat.id)
		selected = bd.get_user_leagues(message.chat.id)
	except Exception as exc:
		logger.error("Ошибка БД: %s", exc)
		await bot.send_message(
			message.chat.id,
			"❌ База данных недоступна. Проверь права на папку data/ в проекте",
		)
		return
	text = (
		"Выбери лиги, за которыми хочешь следить.\n"
		"Нажми ещё раз, чтобы убрать лигу.\n"
		"Уведомления начнут приходить сразу после выбора."
	)
	await bot.send_message(
		message.chat.id,
		text,
		reply_markup=build_league_keyboard(selected),
	)


@bot.message_handler(commands=['leagues'])
async def show_leagues(message):
	try:
		selected = bd.get_user_leagues(message.chat.id)
	except Exception as exc:
		logger.error("Ошибка БД: %s", exc)
		await bot.send_message(message.chat.id, "❌ База данных недоступна")
		return

	if selected:
		text = "Ты следишь за:\n" + "\n".join(f"• {league}" for league in selected)
	else:
		text = "Лиги не выбраны. Используй /match"
	await bot.send_message(message.chat.id, text)


@bot.callback_query_handler(func=lambda call: call.data.startswith("league_"))
async def handle_league_callback(call):
	league_name = call.data.replace("league_", "")
	try:
		added = bd.toggle_user_league(call.message.chat.id, league_name)
	except ValueError:
		await bot.answer_callback_query(call.id, "Неизвестная лига")
		return
	except Exception as exc:
		logger.error("Ошибка БД: %s", exc)
		await bot.answer_callback_query(call.id, "База данных недоступна")
		return

	selected = bd.get_user_leagues(call.message.chat.id)
	status = "добавлена" if added else "убрана"
	await bot.edit_message_reply_markup(
		call.message.chat.id,
		call.message.message_id,
		reply_markup=build_league_keyboard(selected),
	)
	await bot.answer_callback_query(call.id, f"Лига {league_name} {status}")


@bot.message_handler(commands=['matching'])
async def show_matching_status(message):
	try:
		leagues = bd.get_user_leagues(message.chat.id)
	except Exception as exc:
		logger.error("Ошибка БД: %s", exc)
		await bot.send_message(message.chat.id, "❌ База данных недоступна")
		return

	if not leagues:
		await bot.send_message(
			message.chat.id,
			"Сначала выбери лиги через /match",
		)
		return

	await bot.send_message(
		message.chat.id,
		"✅ Мониторинг активен.\n"
		f"Твои лиги: {', '.join(leagues)}\n"
		"Уведомления приходят автоматически всем подписанным пользователям.",
	)


@bot.message_handler(func=lambda message: True)
async def echo_message(message):
	await bot.send_message(message.chat.id, text="Жалобы не принимаются")


async def main():
	try:
		bd.init_db()
	except Exception as exc:
		logger.error("Не удалось подключиться к БД: %s", exc)
		logger.error("Бот запустится, но лиги не будут сохраняться")

	monitor_task = asyncio.create_task(monitor_matches())
	try:
		await bot.polling()
	finally:
		monitor_task.cancel()
		try:
			await monitor_task
		except asyncio.CancelledError:
			pass


if __name__ == "__main__":
	asyncio.run(main())
