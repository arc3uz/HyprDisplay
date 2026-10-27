"""Perfiles de monitores, coincidencia por EDID y estado persistente."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from . import config
from .layout import MonitorState, rules_equal


def fingerprint(monitor: MonitorState) -> str:
    return f"{monitor.description}|{monitor.serial}"


@dataclass
class ProfileMonitor:
    port: str
    fingerprint: str
    rule: dict

    def to_dict(self) -> dict:
        return {
            "port": self.port,
            "fingerprint": self.fingerprint,
            "rule": dict(self.rule),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProfileMonitor":
        return cls(
            port=str(data.get("port", "")),
            fingerprint=str(data.get("fingerprint", "")),
            rule=dict(data.get("rule") or {}),
        )


@dataclass
class Profile:
    name: str
    auto: bool = True
    last_used: int = 0
    primary: str = ""
    monitors: list[ProfileMonitor] = field(default_factory=list)

    @classmethod
    def from_monitors(
        cls,
        name: str,
        monitors: Iterable[MonitorState],
        primary: str = "",
        auto: bool = True,
    ) -> "Profile":
        monitors = list(monitors)
        return cls(
            name=name,
            auto=auto,
            last_used=int(time.time()),
            primary=primary,
            monitors=[
                ProfileMonitor(
                    port=monitor.name,
                    fingerprint=fingerprint(monitor),
                    rule=monitor.to_rule(),
                )
                for monitor in monitors
            ],
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "auto": bool(self.auto),
            "last_used": int(self.last_used),
            "primary": self.primary,
            "monitors": [monitor.to_dict() for monitor in self.monitors],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Profile":
        return cls(
            name=str(data.get("name", "")),
            auto=bool(data.get("auto", True)),
            last_used=int(data.get("last_used") or 0),
            primary=str(data.get("primary", "")),
            monitors=[
                ProfileMonitor.from_dict(item)
                for item in (data.get("monitors") or [])
                if isinstance(item, dict)
            ],
        )

    def match_score(self, monitors: Iterable[MonitorState]) -> int | None:
        """Devuelve una puntuación si el conjunto de monitores coincide, o None."""
        monitors = list(monitors)
        if len(monitors) != len(self.monitors):
            return None

        def search(index: int, used: set[int]) -> int | None:
            if index == len(monitors):
                return 0

            monitor = monitors[index]
            best: int | None = None
            for position, entry in enumerate(self.monitors):
                if position in used:
                    continue

                score: int | None = None
                if entry.fingerprint == fingerprint(monitor):
                    score = 2 if entry.port == monitor.name else 1
                elif (
                    entry.port == monitor.name
                    and entry.fingerprint.split("|", 1)[0] == monitor.description
                ):
                    score = 1

                if score is None:
                    continue

                used.add(position)
                rest = search(index + 1, used)
                used.remove(position)
                if rest is not None:
                    total = score + rest
                    if best is None or total > best:
                        best = total

            return best

        return search(0, set())

    def matches(self, monitors: Iterable[MonitorState]) -> bool:
        return self.match_score(monitors) is not None

    def matches_layout(self, monitors: Iterable[MonitorState]) -> bool:
        """Compara las reglas del perfil con el layout actual de los monitores conectados."""
        monitors = list(monitors)
        by_port = {entry.port: entry.rule for entry in self.monitors}
        current_rules = []
        for monitor in monitors:
            entry = by_port.get(monitor.name)
            if entry is None:
                return False
            current_rules.append(monitor.to_rule())
        return rules_equal(current_rules, [by_port[monitor.name] for monitor in monitors])


class ProfileStore:
    def __init__(self, path: Path | None = None):
        self.path = path or config.profiles_path()
        self.profiles: list[Profile] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.profiles = []
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise config.ConfigError(f"No se pudo leer {self.path}: {exc}") from exc
        self.profiles = [
            Profile.from_dict(item)
            for item in (data.get("profiles") or [])
            if isinstance(item, dict)
        ]

    def save(self) -> None:
        config.atomic_write(
            self.path,
            json.dumps(
                {
                    "version": 1,
                    "profiles": [profile.to_dict() for profile in self.profiles],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )

    def names(self) -> list[str]:
        return [profile.name for profile in self.profiles]

    def get(self, name: str) -> Profile | None:
        for profile in self.profiles:
            if profile.name == name:
                return profile
        return None

    def upsert(self, profile: Profile) -> None:
        for index, existing in enumerate(self.profiles):
            if existing.name == profile.name:
                self.profiles[index] = profile
                return
        self.profiles.append(profile)

    def delete(self, name: str) -> bool:
        before = len(self.profiles)
        self.profiles = [profile for profile in self.profiles if profile.name != name]
        return len(self.profiles) != before

    def match(self, monitors: Iterable[MonitorState]) -> Profile | None:
        monitors = list(monitors)
        candidates: list[tuple[int, int, Profile]] = []
        for profile in self.profiles:
            if not profile.auto:
                continue
            score = profile.match_score(monitors)
            if score is not None:
                candidates.append((score, profile.last_used, profile))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return candidates[0][2]

    def export_to(self, path: Path) -> None:
        config.atomic_write(
            path,
            json.dumps(
                {
                    "version": 1,
                    "profiles": [profile.to_dict() for profile in self.profiles],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )

    def import_from(self, path: Path) -> int:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise config.ConfigError(f"No se pudo importar {path}: {exc}") from exc

        imported = 0
        for item in data.get("profiles") or []:
            if not isinstance(item, dict):
                continue
            profile = Profile.from_dict(item)
            if not profile.name:
                continue
            self.upsert(profile)
            imported += 1
        if imported:
            self.save()
        return imported


@dataclass
class State:
    version: int = 1
    active_profile: str = ""
    primary: str = ""
    current_rules: list[dict] = field(default_factory=list)
    previous_rules: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "active_profile": self.active_profile,
            "primary": self.primary,
            "current_rules": [dict(rule) for rule in self.current_rules],
            "previous_rules": [dict(rule) for rule in self.previous_rules],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "State":
        return cls(
            version=int(data.get("version") or 1),
            active_profile=str(data.get("active_profile") or ""),
            primary=str(data.get("primary") or ""),
            current_rules=[dict(rule) for rule in (data.get("current_rules") or []) if isinstance(rule, dict)],
            previous_rules=[dict(rule) for rule in (data.get("previous_rules") or []) if isinstance(rule, dict)],
        )


class StateStore:
    def __init__(self, path: Path | None = None):
        self.path = path or config.state_path()
        self.state = State()
        self.load()

    def load(self) -> State:
        if not self.path.exists():
            self.state = State()
            return self.state
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise config.ConfigError(f"No se pudo leer {self.path}: {exc}") from exc
        self.state = State.from_dict(data if isinstance(data, dict) else {})
        return self.state

    def save(self, state: State | None = None) -> None:
        if state is not None:
            self.state = state
        config.atomic_write(
            self.path,
            json.dumps(self.state.to_dict(), ensure_ascii=False, indent=2) + "\n",
        )
