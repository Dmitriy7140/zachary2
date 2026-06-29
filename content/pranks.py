"""Лёгкие пакости через RCON: эффекты на выбранного игрока + текст в чат."""
import random
from dataclasses import dataclass

EFFECT_DURATION = 300  # 5 минут на все эффекты


@dataclass(frozen=True)
class Prank:
    key: str
    name: str
    price: int
    kind: str            # "effect" | "sound" | "title" | "summon"
    effect: str = ""
    amp: int = 0
    sound: str = ""
    entity: str = ""
    nbt: str = ""
    count: int = 0
    weapons: tuple = ()  # если задано — каждому мобу случайное оружие в руку
    messages: tuple = ()


# Нитвит по имени «Захар»: профессии нет -> торговать нельзя. Синтаксис под 1.21.1.
ZAHAR_NBT = (
    '{CustomName:\'{"text":"Захар"}\',CustomNameVisible:1b,'
    'VillagerData:{profession:"minecraft:nitwit",type:"minecraft:plains",level:1},'
    'Offers:{Recipes:[]},PersistenceRequired:1b}'
)

# Пиллагер «Злой Захар»: враждебен по умолчанию, агрится на ближайшего игрока.
RAID_NBT = '{CustomName:\'{"text":"Злой Захар"}\',CustomNameVisible:1b,PersistenceRequired:1b}'


# Тексты-открытки на экран для «Написать письмо»
TITLE_PHRASES = [
    "Я тебя вижу 👁",
    "Оглянись...",
    "Ты что-то потерял?",
    "Привет от бати",
    "Зачем ты так?",
    "Беги.",
]


PRANKS: dict[str, Prank] = {
    "warden_roar": Prank(
        "warden_roar", "Крик бати", 3, "sound",
        sound="minecraft:entity.warden.roar",
        messages=(
            "Для {victim} раздался крик бати. Спасибо, {buyer} 🗣",
            "{buyer} одолжил батю на пять минут — теперь {victim} слышит его рёв даже во сне.",
            "Батя {victim} вернулся с работы не в духе. Звукорежиссёр сегодня — {buyer}.",
        ),
    ),
    "blindness": Prank(
        "blindness", "Выключить свет", 15, "effect", effect="blindness",
        messages=(
            "{buyer} выключил {victim} свет. Шарься в темноте 🌑",
            "У {victim} внезапно отключили электричество. Платёж не прошёл, спонсор тьмы — {buyer}.",
            "{victim} моргнул и ничего не увидел. {buyer} просто щёлкнул рубильником.",
        ),
    ),
    "nausea": Prank(
        "nausea", "Купить шаурму", 10, "effect", effect="nausea",
        messages=(
            "{buyer} угостил {victim} шаурмой из подозрительного ларька. Теперь {victim} мутит 🤢",
            "{victim} доел шаурму от {buyer} и пожалел. Желудок передаёт привет.",
            "Шаурма с майонезом трёхдневной свежести — подарок {victim} от {buyer}. Приятного.",
        ),
    ),
    "levitation": Prank(
        "levitation", "Накормить шариками", 50, "effect", effect="levitation",
        messages=(
            "{buyer} накормил {victim} воздушными шариками — того уносит в небо 🎈",
            "{victim} наелся гелия с подачи {buyer} и теперь парит над спавном.",
            "Десять шариков от {buyer} — и {victim} официально нелётная погода.",
        ),
    ),
    "slowness": Prank(
        "slowness", "Постареть на 50 лет", 10, "effect", effect="slowness", amp=4,
        messages=(
            "{buyer} состарил {victim} на полвека. Теперь {victim} ползёт за хлебушком 👴",
            "{victim} внезапно стукнуло 80. Спасибо {buyer} за бесплатный юбилей.",
            "Колени {victim} скрипят, спина не разгибается. {buyer}, ты жесток.",
        ),
    ),
    "fatigue": Prank(
        "fatigue", "Похмелье", 15, "effect", effect="mining_fatigue", amp=2,
        messages=(
            "Вчера {buyer} купил для {victim} литр водки. Тот усосал за один присест — теперь похмелье 🍾",
            "{victim} проснулся с чугунной башкой после вечера с {buyer}. Кирка валится из рук.",
            "{buyer} налил {victim} ещё по одной. Утро добрым не бывает.",
        ),
    ),
    "glowing": Prank(
        "glowing", "Накормить лампочками", 5, "effect", effect="glowing",
        messages=(
            "{buyer} накормил {victim} лампочками — теперь тот светится сквозь стены 💡",
            "{victim} проглотил гирлянду от {buyer}. Спрятаться больше не выйдет.",
            "Внутри {victim} зажёгся свет. Электрик — {buyer}.",
        ),
    ),
    "title": Prank(
        "title", "Написать письмо", 3, "title",
        messages=(
            "{buyer} отправил {victim} письмо. Прямо на сетчатку ✉️",
            "{victim} получил весточку от {buyer}. Не открыть, не закрыть.",
            "Почтальон {buyer} доставил {victim} послание прямо на экран.",
        ),
    ),
    "darkness": Prank(
        "darkness", "Ухудшить зрение", 15, "effect", effect="darkness",
        messages=(
            "{buyer} ухудшил {victim} зрение — в глазах темнеет 🕶",
            "{victim} забыл очки, а {buyer} забрал последние диоптрии. Темно и страшно.",
            "Зрение {victim} упало до минус десяти стараниями {buyer}.",
        ),
    ),
    "zahar": Prank(
        "zahar", "Делегация Захаров", 100, "summon",
        entity="minecraft:villager", nbt=ZAHAR_NBT, count=30,
        messages=(
            "{buyer} прислал {victim} делегацию Захаров — 30 нитвитов обступили жертву и молча смотрят 👁",
            "К {victim} с официальным визитом прибыли 30 Захаров. Торговать отказываются, уходить — тоже. Организатор: {buyer}.",
            "{buyer} вызвал {victim} на ковёр: 30 Захаров окружили и хрюкают. Это надолго.",
        ),
    ),
    "lightning": Prank(
        "lightning", "Шарахнуть молнией", 70, "summon",
        entity="minecraft:lightning_bolt", count=1,
        messages=(
            "{buyer} призвал гнев небес на {victim} — ⚡ БАХ!",
            "В {victim} шарахнула молния от {buyer}. Пахнет жареным.",
            "{buyer} зарядил {victim} молнией. Брови сгорели, шерсть дыбом.",
        ),
    ),
    "zahar_raid": Prank(
        "zahar_raid", "Налет Захаров", 200, "summon",
        entity="minecraft:pillager", nbt=RAID_NBT, count=15,
        weapons=("minecraft:crossbow",),
        messages=(
            "{buyer} натравил на {victim} налёт Захаров — 15 Злых Захаров с арбалетами уже бегут стрелять 🏹",
            "Тревога! 15 Злых Захаров высадились у {victim}. Спасибо {buyer}, теперь беги.",
            "{buyer} устроил {victim} тёплую встречу: 15 разъярённых Захаров открыли огонь.",
        ),
    ),
}


# Иконки для меню пакостей
PRANK_EMOJI = {
    "warden_roar": "🗣",
    "blindness": "🌑",
    "nausea": "🌯",
    "levitation": "🎈",
    "slowness": "👴",
    "fatigue": "🍾",
    "glowing": "💡",
    "title": "✉️",
    "darkness": "🕶",
    "lightning": "⚡",
    "zahar": "🧑‍🌾",
    "zahar_raid": "🏹",
}


def _arm(nbt: str, weapon: str) -> str:
    """Вставить HandItems с оружием перед закрывающей скобкой NBT."""
    hands = f'HandItems:[{{id:"{weapon}",count:1}},{{}}]'
    return f"{nbt[:-1]},{hands}}}"


def prank_commands(p: Prank, nick: str) -> list[str]:
    """RCON-команды для пакости на игрока `nick`."""
    if p.kind == "effect":
        return [f"effect give {nick} {p.effect} {EFFECT_DURATION} {p.amp}"]
    if p.kind == "sound":
        # execute at <ник> — звук в точке игрока, иначе он его не слышит
        return [f"execute at {nick} run playsound {p.sound} master {nick} ~ ~ ~ 100 1 1"]
    if p.kind == "summon":
        if p.weapons:  # каждому мобу — случайное оружие в руку
            return [
                f"execute at {nick} run summon {p.entity} ~ ~ ~ {_arm(p.nbt, random.choice(p.weapons))}"
                for _ in range(p.count)
            ]
        return [f"execute at {nick} run summon {p.entity} ~ ~ ~ {p.nbt}"] * p.count
    if p.kind == "title":
        phrase = random.choice(TITLE_PHRASES)
        return [
            f"title {nick} times 10 80 20",
            f'title {nick} title {{"text":"{phrase}","color":"gold","bold":true}}',
        ]
    return []


def prank_message(p: Prank, victim: str, buyer: str) -> str:
    return random.choice(p.messages).format(victim=victim, buyer=buyer)
