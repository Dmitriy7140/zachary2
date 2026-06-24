"""Фразы для объявлений казино в тред."""
import random

_WINS = [
    "Мать честная, этот сумасшедший {player} выиграл {payout} Z!",
    "{player} обул казино на {payout} Z 🤑",
    "Святые угодники, {player} поймал удачу — +{payout} Z!",
    "{player} крутанул рулетку и сорвал {payout} Z!",
    "Вот это да! {player} забрал {payout} Z из казино.",
    "{player} сегодня везунчик: +{payout} Z 🎰",
    "Казино в шоке — {player} унёс {payout} Z!",
    "{player} поставил и не прогадал: +{payout} Z!",
    "Фортуна улыбнулась {player} — куш {payout} Z!",
    "{player} раздел казино на {payout} Z. Красава!",
    "Ну ничего себе, {player} поднял {payout} Z на ровном месте!",
    "{player} шепнул рулетке нужное слово и забрал {payout} Z.",
]

_LOSSES = [
    "Едрён бобан, {player} всосал все бабки в казино!",
    "{player} спустил {bet} Z в рулетке. Казино передаёт спасибо 🎰",
    "Мда. {player} проиграл {bet} Z. Дома лучше не рассказывать.",
    "{player} сделал ставку и остался без штанов ({bet} Z мимо).",
    "Рулетка скушала {bet} Z у {player} и не подавилась.",
    "{player} поставил, прокрутил, проиграл. Классика. −{bet} Z",
    "Опять не повезло: {player} слил {bet} Z в казино.",
    "{player} кормит казино: −{bet} Z. Когда-нибудь повезёт... наверное.",
    "Фортуна отвернулась от {player}. {bet} Z улетели в трубу.",
    "{player} проверил удачу — удача оказалась занята. −{bet} Z",
    "Казино — 1, {player} — 0. Минус {bet} Z.",
    "{player} занёс {bet} Z и ушёл с пустыми карманами.",
]


def win_msg(player: str, payout: int) -> str:
    return "🎰 " + random.choice(_WINS).format(player=player, payout=payout)


def loss_msg(player: str, bet: int) -> str:
    return "🎰 " + random.choice(_LOSSES).format(player=player, bet=bet)
