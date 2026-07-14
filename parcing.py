import os
import random
import time

import requests
from bs4 import BeautifulSoup
from fake_useragent import UserAgent

from config import AVAILABLE_LEAGUES, MatchEvent, league_matches_tournament


def clear_screen():
	os.system('cls' if os.name == 'nt' else 'clear')


def format_match_text(title: str, time_div, home_score: str, away_score: str) -> str:
	parts = [f"Матч {title}"]
	if time_div and time_div.text:
		parts.append(time_div.text.strip())
	if home_score or away_score:
		parts.append(f"{home_score} - {away_score}")
	return " ".join(parts)


class ParcingSoccer:
	def __init__(self, leagues_to_track: list[str] | None = None, teams_to_track: list[str] | None = None):
		self.url = "https://soccer365.ru/online/"
		self.session = requests.Session()
		self.ua = UserAgent()
		self.session.max_redirects = 3

		self.leagues_to_track = leagues_to_track or list(AVAILABLE_LEAGUES)
		self.teams_to_track = [team.lower() for team in (teams_to_track or [])]

		self.consecutive_errors = 0
		self.max_errors = 5

		self.score_matches: dict[str, list[str]] = {}
		self.previous_matches: dict[str, str] = {}
		self.match_leagues: dict[str, str] = {}
		self.sent_goals: dict = dict()

		self.update_headers()

	def update_headers(self):
		self.session.headers.update({
			'User-Agent': self.ua.random,
			'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
			'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
			'Accept-Encoding': 'gzip, deflate',
			'Connection': 'keep-alive',
			'Cache-Control': 'max-age=0',
			'Upgrade-Insecure-Requests': '1',
		})

	def _get_tournament_name(self, link) -> str | None:
		parent = link.find_parent('div', class_='live_comptt_bd')
		if not parent:
			return None
		header = parent.find('div', class_='block_header')
		if not header:
			return None
		tournament_href = header.find('a')
		if not tournament_href:
			return None
		return tournament_href.get("href")

	def _resolve_league(self, tournament_name: str) -> str | None:
		for league in self.leagues_to_track:
			if league_matches_tournament(league, tournament_name):
				return league
		return None

	def is_league_tracked(self, link) -> bool:
		tournament_name = self._get_tournament_name(link)
		if not tournament_name:
			return False
		return self._resolve_league(tournament_name) is not None

	def is_team_tracked(self, title: str) -> bool:
		if not self.teams_to_track:
			return True
		title_lower = title.lower()
		return any(team in title_lower for team in self.teams_to_track)

	def get_matches(self) -> list[dict]:
		try:
			self.update_headers()
			response = self.session.get(self.url, timeout=15)
			response.encoding = 'utf-8'

			if response.status_code != 200:
				self.consecutive_errors += 1
				print(f"⚠️ Ошибка {response.status_code}, попытка {self.consecutive_errors}")
				return []

			self.consecutive_errors = 0
			soup = BeautifulSoup(response.text, 'html.parser')
			matches = []

			for link in soup.find_all('a', class_='game_link'):
				if not link:
					continue

				tournament_name = self._get_tournament_name(link)
				league = self._resolve_league(tournament_name) if tournament_name else None


				if not league:
					continue

				title = link.get('title')
				if not title or not self.is_team_tracked(title):
					continue

				time_div = link.find(class_='status')
				result_match = link.find(class_='result')
				if not result_match:
					continue

				score = result_match.find_all(class_='gls')
				if len(score) < 2:
					continue

				home_score = score[0].text if score[0].text != '-' else ''
				away_score = score[1].text if score[1].text != '-' else ''

				matches.append({
					'title': title,
					'time': time_div,
					'home_score': home_score,
					'away_score': away_score,
					'league': league,
				})

			return matches

		except requests.exceptions.ConnectionError:
			self.consecutive_errors += 1
			print(f"🔌 Ошибка соединения, попытка {self.consecutive_errors}")
			return []
		except requests.exceptions.Timeout:
			self.consecutive_errors += 1
			print(f"⏱️ Таймаут, попытка {self.consecutive_errors}")
			return []
		except Exception as e:
			self.consecutive_errors += 1
			print(f"❌ Ошибка: {e}, попытка {self.consecutive_errors}")
			return []

	def poll_once(self, interval: int = 10) -> list[MatchEvent]:
		events: list[MatchEvent] = []

		if self.consecutive_errors > self.max_errors:
			time.sleep(interval * 2)
			return events

		matches = self.get_matches()
		if not matches:
			return events

		current_matches: dict[str, str] = {}
		current_scores: dict[str, list[str]] = {}

		for match in matches:
			title = match['title']
			time_div = match['time']
			home_score = match['home_score']
			away_score = match['away_score']
			league = match['league']

			current_scores[title] = [home_score, away_score]
			self.match_leagues[title] = league

			time_text = time_div.text.strip() if time_div and time_div.text else ''
			match_key = f"{home_score}-{away_score}_{time_text}"
			current_matches[title] = match_key

			score_changed = (
				title in self.score_matches
				and self.score_matches[title] != current_scores[title]
			)
			state_changed = (
				title not in self.previous_matches
				or self.previous_matches[title] != match_key
			)


			if score_changed:

				new_home = int(home_score) if home_score else 0
				new_away = int(away_score) if away_score else 0
				old_home = int(self.sent_goals[title][0])
				old_away = int(self.sent_goals[title][1])
				if new_home > old_home or new_away > old_away:
					goal_text = f"⚽ ГООООООЛ в матче {title}! Счет {home_score}:{away_score}"
					print(f"ГООООООЛ в матче {title}! Счет {home_score}:{away_score}")
					events.append(MatchEvent(
						type='goal',
						match_title=title,
						text=goal_text,
						league=league,
					))
					self.sent_goals[title] = [home_score, away_score]
				elif old_home == 0 and old_away == 0 and (new_home > 0 or new_away > 0):
					goal_text = f"Матч {title} начался! Не пропусти гол!)"
					print(f"Матч {title} начался!")
					events.append(MatchEvent(
						type='start',
						match_title=title,
						text=goal_text,
						league=league,
					))
					self.sent_goals[title] = [home_score, away_score]


			if state_changed:
				update_text = format_match_text(title, time_div, home_score, away_score)
				print(f"\n{time.strftime('%H:%M:%S')}")
				print(f"⚽ ОБНОВЛЕНИЕ: {update_text}")
				events.append(MatchEvent(
					type='update',
					match_title=title,
					text=f"⚽ {update_text}",
					league=league,
				))

		self.score_matches = current_scores

		for old_title in list(self.previous_matches.keys()):
			if old_title not in current_matches:
				finished_text = f"❌ МАТЧ ЗАВЕРШЕН: {old_title}"
				print(finished_text)
				events.append(MatchEvent(
					type='finished',
					match_title=old_title,
					text=finished_text,
					league=self.match_leagues.pop(old_title, None),
				))
				if old_title in self.sent_goals:
					del self.sent_goals[old_title]

		self.previous_matches = current_matches
		return events

	def run(self, interval: int = 5):
		print(f"⏱ Обновление каждые {interval} секунд")

		while True:
			try:
				for event in self.poll_once(interval=interval):
					yield event
				time.sleep(interval + random.uniform(-0.5, 0.5))
			except KeyboardInterrupt:
				print("\n\n🛑 Парсер остановлен пользователем")
				break
			except Exception as e:
				print(f"❌ Ошибка в основном цикле: {e}")
				self.consecutive_errors += 1
				time.sleep(interval)


if __name__ == "__main__":
	parser = ParcingSoccer()
	for event in parser.run(interval=8):
		print(event)
