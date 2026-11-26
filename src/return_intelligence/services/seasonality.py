from datetime import datetime

from ..config import DEFAULT_DEMO_CLOCK
from ..domain.models import SeasonalityResult

# Montréal retail calendar (synthetic stores are in Montréal).
SEASON_BY_MONTH = {
    1: 'WINTER', 2: 'WINTER', 3: 'WINTER', 4: 'TRANSITION', 5: 'SUMMER', 6: 'SUMMER',
    7: 'SUMMER', 8: 'SUMMER', 9: 'TRANSITION', 10: 'TRANSITION', 11: 'WINTER', 12: 'WINTER',
}


def season_for_date(dt: datetime) -> str:
    return SEASON_BY_MONTH[dt.month]


class SeasonalityService:
    def __init__(self, season_override=None, clock=None):
        self.season_override = season_override.upper() if season_override else None
        self.clock = clock or (lambda: datetime.fromisoformat(DEFAULT_DEMO_CLOCK))

    @property
    def season(self) -> str:
        return self.current_season()[0]

    def current_season(self) -> tuple[str, str, str]:
        """Return (season, source 'override'|'clock', as_of 'YYYY-MM-DD')."""
        as_of = self.clock()
        if self.season_override:
            return self.season_override, 'override', as_of.date().isoformat()
        return season_for_date(as_of), 'clock', as_of.date().isoformat()

    def evaluate(self, profile: str) -> SeasonalityResult:
        season, source, as_of = self.current_season()
        if profile == 'YEAR_ROUND': flag = 0; reason = 'Year-round shoe is suitable in every season.'
        elif season == 'TRANSITION': flag = 0; reason = 'Transition season treats summer and winter shoes as suitable.'
        elif profile == season: flag = 0; reason = f'{profile.title()} shoe is in season.'
        else: flag = 1; reason = f'{profile.title()} shoe is out of season during {season.title()}.'
        return SeasonalityResult(flag=flag, season=season, reason=reason, source=source, as_of=as_of, profile=profile)
