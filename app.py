import os
import sqlite3
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

MUSTERI, TUTAR, NOT = range(3)

# Veritabanı
conn = sqlite3.connect("odemeler.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS odemeler (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    musteri TEXT NOT NULL,
    tutar REAL NOT NULL,
    notlar TEXT,
    tarih TEXT NOT NULL
)
""")
conn.commit()

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
        "💰 Takım Yıldızı Ödeme Takip\n\n"
        "Yapmak istediğiniz işlemi seçiniz:",
        reply_markup=ana_menu
    )


async def odeme_baslat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏢 Müşteri adını yazınız:")
    return MUSTERI


async def musteri_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["musteri"] = update.message.text
    await update.message.reply_text("💰 Gelen ödeme tutarını yazınız:")
    return TUTAR


async def tutar_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    text = text.replace("₺", "").replace("TL", "").replace("tl", "")
    text = text.replace(".", "").replace(",", ".")

    try:
        tutar = float(text)
    except ValueError:
        await update.message.reply_text(
            "❌ Tutarı anlayamadım.\nÖrnek: 15000"
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

    tarih = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute(
        "INSERT INTO odemeler (musteri, tutar, notlar, tarih) VALUES (?, ?, ?, ?)",
        (musteri, tutar, notlar, tarih)
    )
    conn.commit()

    mesaj = (
        "✅ ÖDEME KAYDEDİLDİ\n\n"
        f"🏢 Müşteri: {musteri}\n"
        f"💰 Ödeme: {tutar:,.2f} ₺\n"
        f"📅 Tarih: {datetime.now().strftime('%d.%m.%Y')}\n"
    )

    if notlar:
        mesaj += f"📝 Not: {notlar}"

    await update.message.reply_text(
        mesaj,
        reply_markup=ana_menu
    )

    context.user_data.clear()

    return ConversationHandler.END


async def bu_hafta(update: Update, context: ContextTypes.DEFAULT_TYPE):

    cursor.execute("""
        SELECT musteri, tutar, notlar, tarih
        FROM odemeler
        WHERE strftime('%Y-%W', tarih) = strftime('%Y-%W', 'now', 'localtime')
        ORDER BY tarih DESC
    """)

    kayitlar = cursor.fetchall()

    if not kayitlar:
        await update.message.reply_text(
            "📋 Bu hafta henüz ödeme kaydı yok.",
            reply_markup=ana_menu
        )
        return

    toplam = 0
    mesaj = "📋 BU HAFTANIN ÖDEMELERİ\n\n"

    for musteri, tutar, notlar, tarih in kayitlar:

        toplam += tutar

        tarih_goster = datetime.strptime(
            tarih,
            "%Y-%m-%d %H:%M:%S"
        ).strftime("%d.%m.%Y")

        mesaj += (
            f"🏢 {musteri}\n"
            f"💰 {tutar:,.2f} ₺\n"
            f"📅 {tarih_goster}\n"
        )

        if notlar:
            mesaj += f"📝 {notlar}\n"

        mesaj += "\n"

    mesaj += f"💵 HAFTALIK TOPLAM: {toplam:,.2f} ₺"

    await update.message.reply_text(mesaj)


async def gecmis(update: Update, context: ContextTypes.DEFAULT_TYPE):

    cursor.execute("""
        SELECT musteri, tutar, notlar, tarih
        FROM odemeler
        ORDER BY tarih DESC
        LIMIT 30
    """)

    kayitlar = cursor.fetchall()

    if not kayitlar:
        await update.message.reply_text("Henüz ödeme kaydı bulunmuyor.")
        return

    mesaj = "🔎 SON ÖDEMELER\n\n"

    for musteri, tutar, notlar, tarih in kayitlar:

        tarih_goster = datetime.strptime(
            tarih,
            "%Y-%m-%d %H:%M:%S"
        ).strftime("%d.%m.%Y")

        mesaj += (
            f"🏢 {musteri}\n"
            f"💰 {tutar:,.2f} ₺\n"
            f"📅 {tarih_goster}\n"
        )

        if notlar:
            mesaj += f"📝 {notlar}\n"

        mesaj += "\n"

    await update.message.reply_text(mesaj)


async def iptal(update: Update, context: ContextTypes.DEFAULT_TYPE):

    context.user_data.clear()

    await update.message.reply_text(
        "İşlem iptal edildi.",
        reply_markup=ana_menu
    )

    return ConversationHandler.END


def main():

    TOKEN = os.environ.get("BOT_TOKEN")

    if not TOKEN:
        raise RuntimeError("BOT_TOKEN bulunamadı.")

    app = Application.builder().token(TOKEN).build()

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

    app.add_handler(CommandHandler("start", start))

    app.add_handler(odeme_conversation)

    app.add_handler(
        MessageHandler(
            filters.Regex("^📋 Bu Haftanın Ödemeleri$"),
            bu_hafta
        )
    )

    app.add_handler(
        MessageHandler(
            filters.Regex("^🔎 Geçmiş Ödemeler$"),
            gecmis
        )
    )

    print("Ödeme takip botu çalışıyor...")

    app.run_polling()


if __name__ == "__main__":
    main()
