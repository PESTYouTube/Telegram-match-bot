import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

PROJECT_DIR = Path(__file__).resolve().parent
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", PROJECT_DIR / "data" / "matchbot.db"))

# Отображаемое имя -> подстроки в названии турнира на soccer365.ru
LEAGUE_PATTERNS: dict[str, list[str]] = {
	"РПЛ": ["Россия. Премьер-лига", "РПЛ", "Российская Премьер-Лига"],
	"Ла Лига": ["Ла Лига", "Испания. Примера"],
	"Лига 1(Франция)": ["Лига 1", "Франция. Лига 1"],
	"АПЛ": ["Англия. Премьер-лига", "АПЛ", "Премьер-лига Англии"],
	"Бундеслига": ["Бундеслига", "Германия. Бундеслига"],
	"Серия А": ["Серия А", "Италия. Серия А"],
	"ЧМ 26": ["Чемпионат мира 2026", "ЧМ-2026", "ЧМ 2026", "Чемпионат мира"],
}

AVAILABLE_LEAGUES = list(LEAGUE_PATTERNS.keys())


@dataclass(frozen=True)
class MatchEvent:
	type: str  # goal | update | finished
	match_title: str
	text: str
	league: str | None = None

	def __str__(self) -> str:
		return self.text


def league_matches_tournament(league_name: str, tournament_name: str) -> bool:
	patterns = LEAGUE_PATTERNS.get(league_name, [])
	return any(pattern.lower() in tournament_name.lower() for pattern in patterns)
