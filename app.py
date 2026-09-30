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
# VERITABANI
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

            cur.execute("""
                ALTER TABLE odemeler
                ADD COLUMN IF NOT EXISTS odeme_turu TEXT
            """)

        conn.commit()


veritabani_hazirla()


# =========================================================
# DURUMLAR
# =========================================================

MUSTERI, TUTAR, ODEME_TURU = range(3)

(
    KAYIT_ID,
    ISLEM_SEC,
    DUZENLEME_SEC,
    YENI_MUSTERI,
    YENI_TUTAR,
    YENI_TUR,
    SIL_ONAY,
) = range(10, 17)


# =========================================================
# MENULER
# =========================================================

ana_menu = ReplyKeyboardMarkup(
    [
        ["💰 Ödeme Ekle"],
        ["📋 Bu Haftanın Ödemeleri"],
        ["🔎 Geçmiş Ödemeler"],
        ["🛠 Geçmiş Kayıt Düzenle / Sil"],
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


islem_menu = ReplyKeyboardMarkup(
    [
        ["✏️ Düzenle", "🗑️ Sil"],
        ["❌ Vazgeç"],
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)


duzenleme_menu = ReplyKeyboardMarkup(
    [
        ["🏢 Müşteri Adı"],
        ["💰 Tutar"],
        ["💳 Ödeme Türü"],
        ["❌ Vazgeç"],
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)


silme_menu = ReplyKeyboardMarkup(
    [
        ["⚠️ Evet, Sil"],
        ["❌ Vazgeç"],
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)


# =========================================================
# YARDIMCI FONKSIYONLAR
# =========================================================

def tutar_cevir(text):
    text = (
        text.strip()
        .replace("₺", "")
        .replace("TL", "")
        .replace("tl", "")
        .replace(" ", "")
    )

    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")

    elif "," in text:
        text = text.replace(",", ".")

    elif "." in text:
        parcalar = text.split(".")

        if len(parcalar[-1]) == 3:
            text = text.replace(".", "")

    tutar = float(text)

    if tutar <= 0:
        raise ValueError

    return tutar


def kayit_getir(kayit_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, musteri, tutar, tarih, odeme_turu
                FROM odemeler
                WHERE id = %s
                """,
                (kayit_id,)
            )

            return cur.fetchone()


def kayit_metni(kayit):
    kayit_id, musteri, tutar, tarih, odeme_turu = kayit

    tur = odeme_turu or "Ödeme türü belirtilmemiş"

    return (
        f"🆔 Kayıt No: {kayit_id}\n"
        f"🏢 Müşteri: {musteri}\n"
        f"💰 Tutar: {float(tutar):,.2f} ₺\n"
        f"💳 Tür: {tur}\n"
        f"📅 Tarih: {tarih.strftime('%d.%m.%Y')}"
    )


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    await update.message.reply_text(
        "💰 TAKIM YILDIZI ÖDEME TAKİP\n\n"
        "Yapmak istediğiniz işlemi seçiniz:",
        reply_markup=ana_menu
    )


# =========================================================
# YENI ODEME
# =========================================================

async def odeme_baslat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

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
    try:
        tutar = tutar_cevir(update.message.text)

    except ValueError:
        await update.message.reply_text(
            "❌ Tutarı anlayamadım.\n"
            "Örneğin 15000 yazınız:"
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

    gecerli = [
        "💵 Nakit",
        "🧾 Faturalı Ödeme",
        "🏦 Şahsi IBAN",
    ]

    if secim not in gecerli:
        await update.message.reply_text(
            "❌ Lütfen butonlardan seçim yapınız.",
            reply_markup=odeme_turu_menu
        )

        return ODEME_TURU

    musteri = context.user_data["musteri"]
    tutar = context.user_data["tutar"]
    tarih = datetime.now()

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO odemeler
                (musteri, tutar, notlar, tarih, odeme_turu)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    musteri,
                    tutar,
                    "",
                    tarih,
                    secim
                )
            )

            kayit_id = cur.fetchone()[0]

        conn.commit()

    await update.message.reply_text(
        "✅ ÖDEME KAYDEDİLDİ\n\n"
        f"🆔 Kayıt No: {kayit_id}\n"
        f"🏢 Müşteri: {musteri}\n"
        f"💰 Ödeme: {tutar:,.2f} ₺\n"
        f"💳 Ödeme Türü: {secim}\n"
        f"📅 Tarih: {tarih.strftime('%d.%m.%Y')}",
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
                SELECT id, musteri, tutar, tarih, odeme_turu
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
    nakit = 0
    faturali = 0
    iban = 0
    belirtilmemis = 0

    mesaj = "📋 BU HAFTANIN ÖDEMELERİ\n\n"

    for kayit_id, musteri, tutar, tarih, tur in kayitlar:
        tutar = float(tutar)
        toplam += tutar

        if tur == "💵 Nakit":
            nakit += tutar
        elif tur == "🧾 Faturalı Ödeme":
            faturali += tutar
        elif tur == "🏦 Şahsi IBAN":
            iban += tutar
        else:
            belirtilmemis += tutar

        mesaj += (
            f"🆔 {kayit_id}\n"
            f"🏢 {musteri}\n"
            f"💰 {tutar:,.2f} ₺\n"
            f"💳 {tur or 'Ödeme türü belirtilmemiş'}\n"
            f"📅 {tarih.strftime('%d.%m.%Y')}\n"
            "────────────\n"
        )

    mesaj += (
        "\n📊 HAFTALIK ÖZET\n\n"
        f"💵 Nakit: {nakit:,.2f} ₺\n"
        f"🧾 Faturalı: {faturali:,.2f} ₺\n"
        f"🏦 Şahsi IBAN: {iban:,.2f} ₺\n"
    )

    if belirtilmemis:
        mesaj += (
            f"❓ Türü belirtilmemiş: "
            f"{belirtilmemis:,.2f} ₺\n"
        )

    mesaj += (
        "\n💰 HAFTALIK GENEL TOPLAM\n"
        f"{toplam:,.2f} ₺"
    )

    await update.message.reply_text(
        mesaj,
        reply_markup=ana_menu
    )


# =========================================================
# GECMIS
# =========================================================

async def gecmis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, musteri, tutar, tarih, odeme_turu
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

    for kayit_id, musteri, tutar, tarih, tur in kayitlar:
        mesaj += (
            f"🆔 Kayıt No: {kayit_id}\n"
            f"🏢 {musteri}\n"
            f"💰 {float(tutar):,.2f} ₺\n"
            f"💳 {tur or 'Ödeme türü belirtilmemiş'}\n"
            f"📅 {tarih.strftime('%d.%m.%Y')}\n"
            "────────────\n"
        )

    await update.message.reply_text(
        mesaj,
        reply_markup=ana_menu
    )


# =========================================================
# DUZENLE / SIL
# =========================================================

async def yonet_baslat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    await update.message.reply_text(
        "🛠 DÜZENLE / SİL\n\n"
        "İşlem yapmak istediğiniz ödemenin "
        "🆔 Kayıt No'sunu yazınız.\n\n"
        "Kayıt numaralarını 🔎 Geçmiş Ödemeler "
        "bölümünden görebilirsiniz."
    )

    return KAYIT_ID


async def kayit_id_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        kayit_id = int(update.message.text.strip())

    except ValueError:
        await update.message.reply_text(
            "❌ Geçerli bir kayıt numarası yazınız.\n"
            "Örnek: 15"
        )

        return KAYIT_ID

    kayit = kayit_getir(kayit_id)

    if not kayit:
        await update.message.reply_text(
            "❌ Bu kayıt numarası bulunamadı.\n"
            "Başka bir kayıt numarası yazınız:"
        )

        return KAYIT_ID

    context.user_data["kayit_id"] = kayit_id

    await update.message.reply_text(
        "📄 SEÇİLEN KAYIT\n\n"
        + kayit_metni(kayit)
        + "\n\nNe yapmak istiyorsunuz?",
        reply_markup=islem_menu
    )

    return ISLEM_SEC


async def islem_sec(update: Update, context: ContextTypes.DEFAULT_TYPE):
    secim = update.message.text.strip()

    if secim == "✏️ Düzenle":
        await update.message.reply_text(
            "✏️ Hangi bilgiyi değiştirmek istiyorsunuz?",
            reply_markup=duzenleme_menu
        )

        return DUZENLEME_SEC

    if secim == "🗑️ Sil":
        kayit = kayit_getir(
            context.user_data["kayit_id"]
        )

        if not kayit:
            await update.message.reply_text(
                "❌ Kayıt artık bulunmuyor.",
                reply_markup=ana_menu
            )

            context.user_data.clear()
            return ConversationHandler.END

        await update.message.reply_text(
            "⚠️ BU KAYIT SİLİNECEK\n\n"
            + kayit_metni(kayit)
            + "\n\nBu işlem geri alınamaz.",
            reply_markup=silme_menu
        )

        return SIL_ONAY

    if secim == "❌ Vazgeç":
        context.user_data.clear()

        await update.message.reply_text(
            "İşlem iptal edildi.",
            reply_markup=ana_menu
        )

        return ConversationHandler.END

    await update.message.reply_text(
        "Lütfen butonlardan seçim yapınız.",
        reply_markup=islem_menu
    )

    return ISLEM_SEC


async def duzenleme_sec(update: Update, context: ContextTypes.DEFAULT_TYPE):
    secim = update.message.text.strip()

    if secim == "🏢 Müşteri Adı":
        await update.message.reply_text(
            "🏢 Yeni müşteri adını yazınız:"
        )

        return YENI_MUSTERI

    if secim == "💰 Tutar":
        await update.message.reply_text(
            "💰 Yeni ödeme tutarını yazınız:"
        )

        return YENI_TUTAR

    if secim == "💳 Ödeme Türü":
        await update.message.reply_text(
            "💳 Yeni ödeme türünü seçiniz:",
            reply_markup=odeme_turu_menu
        )

        return YENI_TUR

    if secim == "❌ Vazgeç":
        context.user_data.clear()

        await update.message.reply_text(
            "İşlem iptal edildi.",
            reply_markup=ana_menu
        )

        return ConversationHandler.END

    await update.message.reply_text(
        "Lütfen butonlardan seçim yapınız.",
        reply_markup=duzenleme_menu
    )

    return DUZENLEME_SEC


async def yeni_musteri(update: Update, context: ContextTypes.DEFAULT_TYPE):
    yeni_ad = update.message.text.strip()

    if not yeni_ad:
        await update.message.reply_text(
            "❌ Müşteri adı boş olamaz."
        )

        return YENI_MUSTERI

    kayit_id = context.user_data["kayit_id"]

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE odemeler
                SET musteri = %s
                WHERE id = %s
                """,
                (yeni_ad, kayit_id)
            )

        conn.commit()

    kayit = kayit_getir(kayit_id)

    await update.message.reply_text(
        "✅ KAYIT GÜNCELLENDİ\n\n"
        + kayit_metni(kayit),
        reply_markup=ana_menu
    )

    context.user_data.clear()

    return ConversationHandler.END


async def yeni_tutar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        yeni_tutar_degeri = tutar_cevir(
            update.message.text
        )

    except ValueError:
        await update.message.reply_text(
            "❌ Tutarı anlayamadım.\n"
            "Örneğin 15000 yazınız:"
        )

        return YENI_TUTAR

    kayit_id = context.user_data["kayit_id"]

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE odemeler
                SET tutar = %s
                WHERE id = %s
                """,
                (yeni_tutar_degeri, kayit_id)
            )

        conn.commit()

    kayit = kayit_getir(kayit_id)

    await update.message.reply_text(
        "✅ KAYIT GÜNCELLENDİ\n\n"
        + kayit_metni(kayit),
        reply_markup=ana_menu
    )

    context.user_data.clear()

    return ConversationHandler.END


async def yeni_tur(update: Update, context: ContextTypes.DEFAULT_TYPE):
    yeni_odeme_turu = update.message.text.strip()

    gecerli = [
        "💵 Nakit",
        "🧾 Faturalı Ödeme",
        "🏦 Şahsi IBAN",
    ]

    if yeni_odeme_turu not in gecerli:
        await update.message.reply_text(
            "❌ Lütfen butonlardan seçim yapınız.",
            reply_markup=odeme_turu_menu
        )

        return YENI_TUR

    kayit_id = context.user_data["kayit_id"]

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE odemeler
                SET odeme_turu = %s
                WHERE id = %s
                """,
                (yeni_odeme_turu, kayit_id)
            )

        conn.commit()

    kayit = kayit_getir(kayit_id)

    await update.message.reply_text(
        "✅ KAYIT GÜNCELLENDİ\n\n"
        + kayit_metni(kayit),
        reply_markup=ana_menu
    )

    context.user_data.clear()

    return ConversationHandler.END


async def sil_onay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    secim = update.message.text.strip()

    if secim == "❌ Vazgeç":
        context.user_data.clear()

        await update.message.reply_text(
            "✅ Silme işlemi iptal edildi.",
            reply_markup=ana_menu
        )

        return ConversationHandler.END

    if secim != "⚠️ Evet, Sil":
        await update.message.reply_text(
            "Lütfen seçim yapınız.",
            reply_markup=silme_menu
        )

        return SIL_ONAY

    kayit_id = context.user_data["kayit_id"]

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM odemeler
                WHERE id = %s
                RETURNING id
                """,
                (kayit_id,)
            )

            silinen = cur.fetchone()

        conn.commit()

    context.user_data.clear()

    if not silinen:
        await update.message.reply_text(
            "❌ Kayıt bulunamadı.",
            reply_markup=ana_menu
        )

        return ConversationHandler.END

    await update.message.reply_text(
        f"🗑️ Kayıt No {kayit_id} silindi.",
        reply_markup=ana_menu
    )

    return ConversationHandler.END


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
# MAIN
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
        },

        fallbacks=[
            CommandHandler("iptal", iptal)
        ],
    )

    yonet_conversation = ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.Regex(
                    "^🛠 Geçmiş Kayıt Düzenle / Sil$"
                ),
                yonet_baslat
            )
        ],

        states={
            KAYIT_ID: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    kayit_id_al
                )
            ],

            ISLEM_SEC: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    islem_sec
                )
            ],

            DUZENLEME_SEC: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    duzenleme_sec
                )
            ],

            YENI_MUSTERI: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    yeni_musteri
                )
            ],

            YENI_TUTAR: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    yeni_tutar
                )
            ],

            YENI_TUR: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    yeni_tur
                )
            ],

            SIL_ONAY: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    sil_onay
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
        yonet_conversation
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
