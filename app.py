import os
import threading
from datetime import datetime

import psycopg
from flask import Flask
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# =========================================================
# RENDER WEB SERVER
# =========================================================

web_app = Flask(__name__)


@web_app.route("/")
def home():
    return "Takim Yildizi Odeme Bot aktif."


def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)


# =========================================================
# POSTGRESQL VERITABANI
# =========================================================

DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL bulunamadi.")


def get_db():
    return psycopg.connect(DATABASE_URL)


def veritabani_hazirla():
    with get_db() as conn:
        with conn.cursor() as cur:

            # Ana tablo
            cur.execute("""
                CREATE TABLE IF NOT EXISTS odemeler (
                    id BIGSERIAL PRIMARY KEY,
                    musteri TEXT NOT NULL,
                    tutar NUMERIC(15, 2) NOT NULL,
                    notlar TEXT,
                    tarih TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Eski kayıtları bozmadan yeni sütunu ekle
            cur.execute("""
                ALTER TABLE odemeler
                ADD COLUMN IF NOT EXISTS odeme_turu TEXT
            """)

        conn.commit()


veritabani_hazirla()


# =========================================================
# TELEGRAM AYARLARI
# =========================================================

MUSTERI, TUTAR, ODEME_TURU, NOT = range(4)

ana_menu = ReplyKeyboardMarkup(
    [
        ["💰 Ödeme Ekle"],
        ["📋 Bu Haftanın Ödemeleri"],
        ["🔎 Geçmiş Ödemeler"],
    ],
    resize_keyboard=True
)

odeme_turu_menu = ReplyKeyboardMarkup(
    [
        ["💵 Nakit"],
        ["🧾 Faturalı Ödeme"],
        ["🏦 Şahsi IBAN"],
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)


# =========================================================
# ANA MENU
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💰 TAKIM YILDIZI ÖDEME TAKİP\n\n"
        "Yapmak istediğiniz işlemi seçiniz:",
        reply_markup=ana_menu
    )


# =========================================================
# ODEME EKLE
# =========================================================

async def odeme_baslat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏢 Müşteri adını yazınız:"
    )

    return MUSTERI


async def musteri_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["musteri"] = update.message.text.strip()

    await update.message.reply_text(
        "💰 Gelen ödeme tutarını yazınız:\n\n"
        "Örnek: 15000"
    )

    return TUTAR


async def tutar_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    text = (
        text.replace("₺", "")
        .replace("TL", "")
        .replace("tl", "")
        .replace(" ", "")
    )

    # 15.000 / 15,000 / 15000 gibi girişleri kabul eder
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    elif "." in text:
        parcalar = text.split(".")
        if len(parcalar[-1]) == 3:
            text = text.replace(".", "")

    try:
        tutar = float(text)

        if tutar <= 0:
            raise ValueError

    except ValueError:
        await update.message.reply_text(
            "❌ Tutarı anlayamadım.\n\n"
            "Örneğin sadece 15000 yazabilirsiniz:"
        )

        return TUTAR

    context.user_data["tutar"] = tutar

    await update.message.reply_text(
        "💳 Ödeme türünü seçiniz:",
        reply_markup=odeme_turu_menu
    )

    return ODEME_TURU


async def odeme_turu_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    secim = update.message.text.strip()

    gecerli_turler = [
        "💵 Nakit",
        "🧾 Faturalı Ödeme",
        "🏦 Şahsi IBAN",
    ]

    if secim not in gecerli_turler:
        await update.message.reply_text(
            "❌ Lütfen aşağıdaki butonlardan bir ödeme türü seçiniz.",
            reply_markup=odeme_turu_menu
        )

        return ODEME_TURU

    context.user_data["odeme_turu"] = secim

    await update.message.reply_text(
        "📝 Notunuzu yazınız.\n\n"
        "Not eklemek istemiyorsanız - yazabilirsiniz:",
        reply_markup=ReplyKeyboardRemove()
    )

    return NOT


async def not_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    notlar = update.message.text.strip()

    if notlar == "-":
        notlar = ""

    musteri = context.user_data["musteri"]
    tutar = context.user_data["tutar"]
    odeme_turu = context.user_data["odeme_turu"]

    tarih = datetime.now()

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO odemeler
                (musteri, tutar, notlar, tarih, odeme_turu)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    musteri,
                    tutar,
                    notlar,
                    tarih,
                    odeme_turu
                )
            )

        conn.commit()

    mesaj = (
        "✅ ÖDEME KAYDEDİLDİ\n\n"
        f"🏢 Müşteri: {musteri}\n"
        f"💰 Ödeme: {tutar:,.2f} ₺\n"
        f"💳 Ödeme Türü: {odeme_turu}\n"
        f"📅 Tarih: {tarih.strftime('%d.%m.%Y')}\n"
    )

    if notlar:
        mesaj += f"📝 Not: {notlar}\n"

    await update.message.reply_text(
        mesaj,
        reply_markup=ana_menu
    )

    context.user_data.clear()

    return ConversationHandler.END


# =========================================================
# BU HAFTANIN ODEMELERI
# =========================================================

async def bu_hafta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    simdi = datetime.now()

    yil, hafta, _ = simdi.isocalendar()

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    musteri,
                    tutar,
                    notlar,
                    tarih,
                    odeme_turu
                FROM odemeler
                WHERE EXTRACT(ISOYEAR FROM tarih) = %s
                AND EXTRACT(WEEK FROM tarih) = %s
                ORDER BY tarih DESC
                """,
                (yil, hafta)
            )

            kayitlar = cur.fetchall()

    if not kayitlar:
        await update.message.reply_text(
            "📋 Bu hafta henüz ödeme kaydı yok.",
            reply_markup=ana_menu
        )

        return

    toplam = 0
    nakit_toplam = 0
    faturali_toplam = 0
    iban_toplam = 0
    eski_toplam = 0

    mesaj = "📋 BU HAFTANIN ÖDEMELERİ\n\n"

    for musteri, tutar, notlar, tarih, odeme_turu in kayitlar:
        tutar = float(tutar)

        toplam += tutar

        if odeme_turu == "💵 Nakit":
            nakit_toplam += tutar

        elif odeme_turu == "🧾 Faturalı Ödeme":
            faturali_toplam += tutar

        elif odeme_turu == "🏦 Şahsi IBAN":
            iban_toplam += tutar

        else:
            # Yeni özellik eklenmeden önceki kayıtlar
            eski_toplam += tutar

        mesaj += (
            f"🏢 {musteri}\n"
            f"💰 {tutar:,.2f} ₺\n"
        )

        if odeme_turu:
            mesaj += f"💳 {odeme_turu}\n"
        else:
            mesaj += "💳 Ödeme türü belirtilmemiş\n"

        mesaj += f"📅 {tarih.strftime('%d.%m.%Y')}\n"

        if notlar:
            mesaj += f"📝 {notlar}\n"

        mesaj += "────────────\n"

    mesaj += (
        "\n"
        "📊 HAFTALIK ÖZET\n\n"
        f"💵 Nakit: {nakit_toplam:,.2f} ₺\n"
        f"🧾 Faturalı: {faturali_toplam:,.2f} ₺\n"
        f"🏦 Şahsi IBAN: {iban_toplam:,.2f} ₺\n"
    )

    if eski_toplam > 0:
        mesaj += (
            f"❓ Türü belirtilmemiş: "
            f"{eski_toplam:,.2f} ₺\n"
        )

    mesaj += (
        "\n"
        "💰 HAFTALIK GENEL TOPLAM\n"
        f"{toplam:,.2f} ₺"
    )

    await update.message.reply_text(
        mesaj,
        reply_markup=ana_menu
    )


# =========================================================
# GECMIS ODEMELER
# =========================================================

async def gecmis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    musteri,
                    tutar,
                    notlar,
                    tarih,
                    odeme_turu
                FROM odemeler
                ORDER BY id DESC
                LIMIT 30
            """)

            kayitlar = cur.fetchall()

    if not kayitlar:
        await update.message.reply_text(
            "Henüz ödeme kaydı bulunmuyor.",
            reply_markup=ana_menu
        )

        return

    mesaj = "🔎 SON ÖDEMELER\n\n"

    for musteri, tutar, notlar, tarih, odeme_turu in kayitlar:
        tutar = float(tutar)

        mesaj += (
            f"🏢 {musteri}\n"
            f"💰 {tutar:,.2f} ₺\n"
        )

        if odeme_turu:
            mesaj += f"💳 {odeme_turu}\n"
        else:
            mesaj += "💳 Ödeme türü belirtilmemiş\n"

        mesaj += f"📅 {tarih.strftime('%d.%m.%Y')}\n"

        if notlar:
            mesaj += f"📝 {notlar}\n"

        mesaj += "────────────\n"

    await update.message.reply_text(
        mesaj,
        reply_markup=ana_menu
    )


# =========================================================
# IPTAL
# =========================================================

async def iptal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    await update.message.reply_text(
        "❌ İşlem iptal edildi.",
        reply_markup=ana_menu
    )

    return ConversationHandler.END


# =========================================================
# BOTU BASLAT
# =========================================================

def main():
    TOKEN = os.environ.get("BOT_TOKEN")

    if not TOKEN:
        raise RuntimeError("BOT_TOKEN bulunamadi.")

    application = (
        Application.builder()
        .token(TOKEN)
        .build()
    )

    odeme_conversation = ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.Regex("^💰 Ödeme Ekle$"),
                odeme_baslat
            )
        ],

        states={
            MUSTERI: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    musteri_al
                )
            ],

            TUTAR: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    tutar_al
                )
            ],

            ODEME_TURU: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    odeme_turu_al
                )
            ],

            NOT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    not_al
                )
            ],
        },

        fallbacks=[
            CommandHandler("iptal", iptal)
        ],
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        odeme_conversation
    )

    application.add_handler(
        MessageHandler(
            filters.Regex("^📋 Bu Haftanın Ödemeleri$"),
            bu_hafta
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex("^🔎 Geçmiş Ödemeler$"),
            gecmis
        )
    )

    print("Takim Yildizi Odeme Bot baslatiliyor...")

    application.run_polling()


if __name__ == "__main__":
    web_thread = threading.Thread(
        target=run_web,
        daemon=True
    )

    web_thread.start()

    main()
