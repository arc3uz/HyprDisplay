"""Generación del archivo Lua que Hyprland carga y de los comandos de eval."""

from __future__ import annotations

from typing import Iterable

from .profiles import Profile, State


def lua_quote(value: object) -> str:
    text = str(value)
    text = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{text}"'


def lua_number(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:g}"


def _rule_fields(rule: dict) -> list[tuple[str, str]]:
    return [
        ("output", lua_quote(rule.get("output", ""))),
        ("mode", lua_quote(rule.get("mode", "preferred"))),
        ("position", lua_quote(rule.get("position", "0x0"))),
        ("scale", lua_number(rule.get("scale", 1.0))),
        ("transform", str(int(rule.get("transform", 0)))),
        ("mirror", lua_quote(rule.get("mirror", "") or "")),
        ("disabled", "true" if rule.get("disabled") else "false"),
    ]


def rule_to_lua(rule: dict, indent: str = "    ") -> str:
    lines = [f"{indent}    {key} = {value}," for key, value in _rule_fields(rule)]
    return "{\n" + "\n".join(lines) + f"\n{indent}}}"


def rules_to_eval(rules: Iterable[dict]) -> str:
    """Código que se envía a hyprctl eval para aplicar reglas en caliente."""
    lines = ["do"]
    for rule in rules:
        lines.append("    hl.monitor({")
        for key, value in _rule_fields(rule):
            lines.append(f"        {key} = {value},")
        lines.append("    })")
    lines.append("end")
    return "\n".join(lines)


AUTO_APPLY_CODE = """
local function apply_rules(rules)
    -- Hyprland no crea el wl_output de un monitor que se habilita directamente
    -- en modo espejo. Si la salida está desactivada, se enciende primero sin
    -- espejo y la regla definitiva se aplica un instante después.
    local disabled = {}
    for _, monitor in ipairs(hl.get_monitors({ all = true })) do
        if monitor.disabled then
            disabled[monitor.name] = true
        end
    end

    local pre = {}
    local rest = {}
    for _, rule in ipairs(rules) do
        rest[#rest + 1] = rule
        if not rule.disabled and rule.mirror and rule.mirror ~= "" and disabled[rule.output] then
            local copy = {}
            for key, value in pairs(rule) do
                copy[key] = value
            end
            copy.mirror = ""
            pre[#pre + 1] = copy
        end
    end

    if #pre == 0 then
        for _, rule in ipairs(rest) do
            hl.monitor(rule)
        end
        return
    end

    for _, rule in ipairs(pre) do
        hl.monitor(rule)
    end
    hl.timer(function()
        for _, rule in ipairs(rest) do
            hl.monitor(rule)
        end
    end, { timeout = 300, type = "oneshot" })
end

local function apply_profile(profile)
    local rules = {}
    for _, entry in ipairs(profile.monitors) do
        rules[#rules + 1] = entry.rule
    end
    apply_rules(rules)
end

local function monitor_fingerprint(monitor)
    return tostring(monitor.description or "") .. "|" .. tostring(monitor.serial or "")
end

local function connected_monitors()
    local result = {}
    for _, monitor in ipairs(hl.get_monitors({ all = true })) do
        result[#result + 1] = {
            fingerprint = monitor_fingerprint(monitor),
            port = monitor.name,
        }
    end
    return result
end

local function find_matching_profile()
    local connected = connected_monitors()
    local best = nil
    local best_score = -1

    for _, profile in ipairs(profiles) do
        if profile.auto and #profile.monitors == #connected then
            local used = {}
            local score = 0
            local valid = true

            for _, monitor in ipairs(connected) do
                local match = nil
                for index, entry in ipairs(profile.monitors) do
                    if not used[index] and entry.fingerprint == monitor.fingerprint then
                        match = index
                        score = score + (entry.port == monitor.port and 2 or 1)
                        break
                    end
                end

                if not match then
                    valid = false
                    break
                end
                used[match] = true
            end

            if valid and score > best_score then
                best = profile
                best_score = score
            end
        end
    end

    return best
end

local generation = 0

local function schedule_auto_apply()
    generation = generation + 1
    local expected = generation
    hl.timer(function()
        if expected ~= generation then
            return
        end
        local profile = find_matching_profile()
        if profile then
            apply_profile(profile)
        end
    end, { timeout = 750, type = "oneshot" })
end

hl.on("monitor.added", schedule_auto_apply)
hl.on("monitor.removed", schedule_auto_apply)
hl.on("hyprland.start", schedule_auto_apply)

apply_rules(current)
""".strip()


def generate(profiles: Iterable[Profile], state: State) -> str:
    profiles = list(profiles)
    lines: list[str] = [
        "-- Generated by HyprDisplay. Do not edit manually.",
        "-- Regenerate from the app or with: hyprdisplay apply <perfil>",
        "",
        "local current = {",
    ]

    for rule in state.current_rules:
        lines.append("    " + rule_to_lua(rule, indent="    ") + ",")

    lines.extend(["}", "", "local profiles = {"])

    for profile in profiles:
        lines.extend(
            [
                "    {",
                f"        name = {lua_quote(profile.name)},",
                f"        auto = {'true' if profile.auto else 'false'},",
                f"        last_used = {int(profile.last_used)},",
                f"        primary = {lua_quote(profile.primary)},",
                "        monitors = {",
            ]
        )
        for entry in profile.monitors:
            lines.extend(
                [
                    "            {",
                    f"                port = {lua_quote(entry.port)},",
                    f"                fingerprint = {lua_quote(entry.fingerprint)},",
                    "                rule = " + rule_to_lua(entry.rule, indent="                ") + ",",
                    "            },",
                ]
            )
        lines.extend(["        },", "    },"])

    lines.extend(["}", "", AUTO_APPLY_CODE, ""])
    return "\n".join(lines)
