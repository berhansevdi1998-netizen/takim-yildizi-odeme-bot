import os
import threading
from datetime import datetime

import psycopg
from flask import Flask
from telegram import Update, ReplyKeyboardMarkup
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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS odemeler (
                    id BIGSERIAL PRIMARY KEY,
                    musteri TEXT NOT NULL,
                    tutar NUMERIC(15, 2) NOT NULL,
                    notlar TEXT,
                    tarih TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
        conn.commit()


veritabani_hazirla()


# =========================================================
# TELEGRAM
# =========================================================

MUSTERI, TUTAR, NOT = range(3)

ana_menu = ReplyKeyboardMarkup(
    [
        ["💰 Ödeme Ekle"],
        ["📋 Bu Haftanın Ödemeleri"],
        ["🔎 Geçmiş Ödemeler"],
    ],
    resize_keyboard=True
)


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
        "📝 Notunuzu yazınız.\n\n"
        "Not eklemek istemiyorsanız - yazabilirsiniz:"
    )

    return NOT


async def not_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    notlar = update.message.text.strip()

    if notlar == "-":
        notlar = ""

    musteri = context.user_data["musteri"]
    tutar = context.user_data["tutar"]

    tarih = datetime.now()

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO odemeler
                (musteri, tutar, notlar, tarih)
                VALUES (%s, %s, %s, %s)
                """,
                (musteri, tutar, notlar, tarih)
            )
        conn.commit()

    mesaj = (
        "✅ ÖDEME KAYDEDİLDİ\n\n"
        f"🏢 Müşteri: {musteri}\n"
        f"💰 Ödeme: {tutar:,.2f} ₺\n"
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
            cur.execute("""
                SELECT musteri, tutar, notlar, tarih
                FROM odemeler
                WHERE EXTRACT(ISOYEAR FROM tarih) = %s
                AND EXTRACT(WEEK FROM tarih) = %s
                ORDER BY tarih DESC
            """, (yil, hafta))

            kayitlar = cur.fetchall()

    if not kayitlar:
        await update.message.reply_text(
            "📋 Bu hafta henüz ödeme kaydı yok.",
            reply_markup=ana_menu
        )
        return

    toplam = 0

    mesaj = "📋 BU HAFTANIN ÖDEMELERİ\n\n"

    for musteri, tutar, notlar, tarih in kayitlar:
        tutar = float(tutar)
        toplam += tutar

        mesaj += (
            f"🏢 {musteri}\n"
            f"💰 {tutar:,.2f} ₺\n"
            f"📅 {tarih.strftime('%d.%m.%Y')}\n"
        )

        if notlar:
            mesaj += f"📝 {notlar}\n"

        mesaj += "────────────\n"

    mesaj += (
        "\n"
        "💵 HAFTALIK TOPLAM\n"
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
                SELECT musteri, tutar, notlar, tarih
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

    for musteri, tutar, notlar, tarih in kayitlar:
        tutar = float(tutar)

        mesaj += (
            f"🏢 {musteri}\n"
            f"💰 {tutar:,.2f} ₺\n"
            f"📅 {tarih.strftime('%d.%m.%Y')}\n"
        )

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
