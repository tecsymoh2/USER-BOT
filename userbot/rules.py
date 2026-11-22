"""Pure helpers: keyword rules, M-Pesa parsing, reaction picking, time parsing."""
import re
from datetime import datetime, timedelta, timezone

SENSITIVE = re.compile(r"\b(otp|one[- ]time|verification code|login code|password|passcode|pin|cvv|card number|account number|paybill|"
                       r"till number|send (me )?(some )?(money|cash)|loan|bank details|m-?pesa pin|seed phrase|private key)\b", re.I)
URGENT = re.compile(r"\b(urgent|urgently|asap|emergency|immediately|right now|hospital|accident|please call|call me now|help me|it'?s important)\b", re.I)
SCAM = re.compile(r"(airdrop|giveaway|double your|guaranteed (profit|returns)|investment opportunity|crypto signal|claim your (prize|reward)|"
                  r"you(?:'ve| have) won|verify your account|account (suspended|blocked|locked)|bit\.ly|tinyurl|t\.me/\+|wa\.me/)", re.I)
SPAM = re.compile(r"(airdrop|crypto|forex|binary options|earn \$?\d+ (daily|per day)|dm me for|investment|casino|betting tips|whatsapp me)", re.I)
MPESA = re.compile(r"(?P<code>[A-Z0-9]{10})\s+Confirmed\.?\s*(?:You have received\s+)?Ksh\.?\s?(?P<amt>[\d,]+(?:\.\d{1,2})?)\s+"
                   r"(?P<dir>sent to|paid to|from)\s+(?P<party>.+?)(?:\s+on\s+\d|\.\s|\s+for account|$)", re.I | re.S)

EMOJI = ["👍", "❤️", "🔥", "😂", "🎉", "🙏", "👏", "😍", "😮", "😢", "🤝", "💯", "🥰", "👌"]
_LITE = [  # (pattern, emoji): first match wins
    (re.compile(r"\b(thanks|thank you|asante|shukran|thx|appreciate)\b", re.I), "🙏"),
    (re.compile(r"\b(congrat|congratulations|hongera|we won|i passed|got the job|promotion)\b", re.I), "🎉"),
    (re.compile(r"\b(happy birthday|birthday)\b", re.I), "🎉"),
    (re.compile(r"\b(lol|haha|lmao|😂|🤣|funny)\b", re.I), "😂"),
    (re.compile(r"\b(love you|miss you|i love|my love|babe)\b", re.I), "❤️"),
    (re.compile(r"\b(sorry to hear|passed away|rip|sad news|i'?m sick|not feeling well)\b", re.I), "😢"),
    (re.compile(r"\b(great|awesome|amazing|well done|good job|nice one|poa|safi)\b", re.I), "🔥"),
    (re.compile(r"\b(ok|okay|sure|deal|agreed|sawa|noted|got it|done)\b", re.I), "👍"),
    (re.compile(r"\b(wow|really\?|no way|omg)\b", re.I), "😮"),
]


def lite_reaction(text):
    for pat, emoji in _LITE:
        if pat.search(text or ""):
            return emoji
    return None


def parse_mpesa(text):
    m = MPESA.search(text or "")
    if not m:
        return None
    amt = float(m.group("amt").replace(",", ""))
    d = m.group("dir").lower()
    return {"code": m.group("code").upper(), "amount": amt, "direction": "in" if d == "from" else "out",
            "party": " ".join(m.group("party").split())[:80]}


def parse_duration(s):
    m = re.fullmatch(r"(\d{1,3})\s*([mhd])", (s or "").strip().lower())
    return int(m.group(1)) * {"m": 60, "h": 3600, "d": 86400}[m.group(2)] if m else None


def parse_when(text, now_ts, tz_hours):
    """'30m' | '2h' | '1d' | 'HH:MM' (today/tomorrow, your time) | 'YYYY-MM-DD HH:MM'.
    Returns (timestamp, rest_of_text) or (None, text)."""
    parts = text.strip().split(None, 2)
    if not parts:
        return None, text
    d = parse_duration(parts[0])
    if d:
        return now_ts + d, " ".join(parts[1:])
    local = datetime.fromtimestamp(now_ts, timezone.utc) + timedelta(hours=tz_hours)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[0]) and len(parts) > 1 and re.fullmatch(r"\d{1,2}:\d{2}", parts[1]):
        try:
            dt = datetime.strptime(f"{parts[0]} {parts[1]}", "%Y-%m-%d %H:%M")
        except ValueError:
            return None, text
        return (dt - timedelta(hours=tz_hours)).replace(tzinfo=timezone.utc).timestamp(), " ".join(text.split()[2:])
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", parts[0])
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        target = local.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        if target <= local:
            target += timedelta(days=1)
        return (target - timedelta(hours=tz_hours)).replace(tzinfo=timezone.utc).timestamp(), " ".join(parts[1:])
    return None, text
